//! Authenticated Unix-socket transport for the Chrome extension debugger proxy.

use crate::error::CdpError;
use crate::event::CdpEvent;
use crate::ids::CdpSessionId;
use crate::transport::CdpTransport;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::future::Future;
use std::path::Path;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::UnixStream;
use tokio::sync::{broadcast, mpsc, oneshot};
use tokio::task::JoinHandle;

const PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 8 * 1024 * 1024;
const COMMAND_QUEUE_CAPACITY: usize = 128;
const EVENT_CHANNEL_CAPACITY: usize = 1024;

struct OutboundCommand {
    request_id: u64,
    attachment_id: String,
    session_id: String,
    method: String,
    params: Value,
}

struct TransportState {
    connected: AtomicBool,
    pending: Mutex<HashMap<u64, oneshot::Sender<Result<Value, CdpError>>>>,
}

/// CDP transport pinned to one user-confirmed extension tab attachment.
///
/// The Python bridge owns Native Messaging and forwards only versioned,
/// authenticated messages to this Unix socket. This transport never listens
/// on a network interface and never changes its attachment target.
pub struct ExtensionCdpTransport {
    attachment_id: String,
    session_id: CdpSessionId,
    next_request_id: AtomicU64,
    command_timeout: Duration,
    state: Arc<TransportState>,
    command_tx: mpsc::Sender<OutboundCommand>,
    event_tx: broadcast::Sender<CdpEvent>,
    tasks: Mutex<Vec<JoinHandle<()>>>,
}

impl ExtensionCdpTransport {
    /// Connect to the owner-only bridge socket and negotiate protocol v1.
    pub async fn connect(
        socket_path: &Path,
        token: &str,
        attachment_id: String,
        session_id: CdpSessionId,
        command_timeout: Duration,
    ) -> Result<Self, CdpError> {
        if !socket_path.is_absolute() {
            return Err(CdpError::ExtensionBridge(
                "bridge socket path must be absolute".to_string(),
            ));
        }
        if token.is_empty() || token.len() > 512 {
            return Err(CdpError::ExtensionBridge(
                "bridge authentication token is invalid".to_string(),
            ));
        }
        validate_identifier("attachment ID", &attachment_id)?;
        validate_identifier("session ID", session_id.as_str())?;

        let stream = UnixStream::connect(socket_path)
            .await
            .map_err(|error| CdpError::ExtensionBridge(error.to_string()))?;
        let (mut reader, mut writer) = stream.into_split();
        write_frame(
            &mut writer,
            &json!({
                "type": "runtime.auth",
                "role": "browser_backend",
                "token": token,
            }),
        )
        .await?;
        write_frame(
            &mut writer,
            &json!({
                "protocolVersion": PROTOCOL_VERSION,
                "type": "backend.hello",
                "payload": {
                    "attachmentId": attachment_id,
                    "sessionId": session_id.as_str(),
                },
            }),
        )
        .await?;
        let ready = read_frame(&mut reader).await?;
        if ready.get("type").and_then(Value::as_str) != Some("backend.ready")
            || ready.get("protocolVersion").and_then(Value::as_u64) != Some(PROTOCOL_VERSION)
        {
            return Err(CdpError::ExtensionBridge(
                "bridge did not negotiate protocol v1".to_string(),
            ));
        }

        let (command_tx, command_rx) = mpsc::channel(COMMAND_QUEUE_CAPACITY);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);
        let state = Arc::new(TransportState {
            connected: AtomicBool::new(true),
            pending: Mutex::new(HashMap::new()),
        });
        let reader_task = tokio::spawn(reader_task(reader, Arc::clone(&state), event_tx.clone()));
        let writer_task = tokio::spawn(writer_task(writer, command_rx, Arc::clone(&state)));

        Ok(Self {
            attachment_id,
            session_id,
            next_request_id: AtomicU64::new(1),
            command_timeout,
            state,
            command_tx,
            event_tx,
            tasks: Mutex::new(vec![reader_task, writer_task]),
        })
    }

    async fn command_inner(
        &self,
        session: Option<&CdpSessionId>,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, CdpError> {
        if !self.is_connected() {
            return Err(CdpError::ConnectionLost);
        }
        if let Some(session) = session {
            if session != &self.session_id {
                return Err(CdpError::ExtensionBridge(
                    "command session does not match the confirmed tab attachment".to_string(),
                ));
            }
        }

        let request_id = self.next_request_id.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver) = oneshot::channel();
        self.state
            .pending
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .insert(request_id, sender);
        let command = OutboundCommand {
            request_id,
            attachment_id: self.attachment_id.clone(),
            session_id: self.session_id.as_str().to_string(),
            method: method.to_string(),
            params,
        };
        if self.command_tx.send(command).await.is_err() {
            remove_pending(&self.state, request_id);
            return Err(CdpError::ConnectionLost);
        }

        match tokio::time::timeout(timeout, receiver).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err(CdpError::ConnectionLost),
            Err(_) => {
                remove_pending(&self.state, request_id);
                Err(CdpError::CommandTimeout {
                    method: method.to_string(),
                    timeout,
                })
            }
        }
    }
}

impl CdpTransport for ExtensionCdpTransport {
    fn command<'a>(
        &'a self,
        method: &'a str,
        params: Value,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
        Box::pin(self.command_inner(None, method, params, self.command_timeout))
    }

    fn command_in_session<'a>(
        &'a self,
        session: &'a CdpSessionId,
        method: &'a str,
        params: Value,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
        Box::pin(self.command_inner(Some(session), method, params, self.command_timeout))
    }

    fn command_with_timeout<'a>(
        &'a self,
        session: Option<&'a CdpSessionId>,
        method: &'a str,
        params: Value,
        timeout: Duration,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
        Box::pin(self.command_inner(session, method, params, timeout))
    }

    fn subscribe(&self) -> broadcast::Receiver<CdpEvent> {
        self.event_tx.subscribe()
    }

    fn is_connected(&self) -> bool {
        self.state.connected.load(Ordering::SeqCst)
    }

    fn pending_commands(&self) -> usize {
        self.state
            .pending
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .len()
    }

    fn close<'a>(&'a self) -> Pin<Box<dyn Future<Output = ()> + Send + 'a>> {
        Box::pin(async move {
            self.state.connected.store(false, Ordering::SeqCst);
            fail_pending(&self.state, CdpError::Shutdown);
            let tasks = {
                let mut tasks = self.tasks.lock().unwrap_or_else(|error| error.into_inner());
                std::mem::take(&mut *tasks)
            };
            for task in tasks {
                task.abort();
            }
        })
    }
}

impl Drop for ExtensionCdpTransport {
    fn drop(&mut self) {
        self.state.connected.store(false, Ordering::SeqCst);
        let tasks = self
            .tasks
            .get_mut()
            .unwrap_or_else(|error| error.into_inner());
        for task in tasks.drain(..) {
            task.abort();
        }
    }
}

async fn writer_task(
    mut writer: tokio::net::unix::OwnedWriteHalf,
    mut commands: mpsc::Receiver<OutboundCommand>,
    state: Arc<TransportState>,
) {
    while let Some(command) = commands.recv().await {
        let message = json!({
            "protocolVersion": PROTOCOL_VERSION,
            "type": "backend.command",
            "requestId": command.request_id,
            "payload": {
                "attachmentId": command.attachment_id,
                "sessionId": command.session_id,
                "method": command.method,
                "params": command.params,
            },
        });
        if write_frame(&mut writer, &message).await.is_err() {
            break;
        }
    }
    state.connected.store(false, Ordering::SeqCst);
    fail_pending(&state, CdpError::ConnectionLost);
}

async fn reader_task(
    mut reader: tokio::net::unix::OwnedReadHalf,
    state: Arc<TransportState>,
    event_tx: broadcast::Sender<CdpEvent>,
) {
    loop {
        let message = match read_frame(&mut reader).await {
            Ok(message) => message,
            Err(_) => break,
        };
        match message.get("type").and_then(Value::as_str) {
            Some("backend.response") => handle_response(&state, &message),
            Some("backend.event") => handle_event(&event_tx, &message),
            Some("backend.detached") => break,
            _ => break,
        }
    }
    state.connected.store(false, Ordering::SeqCst);
    fail_pending(&state, CdpError::ConnectionLost);
    let _ = event_tx.send(CdpEvent::ConnectionLost);
}

fn handle_response(state: &TransportState, message: &Value) {
    let Some(request_id) = message.get("requestId").and_then(Value::as_u64) else {
        return;
    };
    let sender = state
        .pending
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .remove(&request_id);
    if let Some(sender) = sender {
        let result = if let Some(result) = message.get("result") {
            Ok(result.clone())
        } else if let Some(error) = message.get("error").and_then(Value::as_str) {
            Err(CdpError::ExtensionBridge(error.to_string()))
        } else {
            Err(CdpError::Unexpected(
                "backend response has neither result nor error".to_string(),
            ))
        };
        let _ = sender.send(result);
    }
}

fn handle_event(event_tx: &broadcast::Sender<CdpEvent>, message: &Value) {
    let Some(method) = message.get("method").and_then(Value::as_str) else {
        return;
    };
    let mut event = json!({
        "method": method,
        "params": message.get("params").cloned().unwrap_or_else(|| json!({})),
    });
    if let Some(session_id) = message.get("sessionId").and_then(Value::as_str) {
        event["sessionId"] = Value::String(session_id.to_string());
    }
    let _ = event_tx.send(CdpEvent::parse(&event));
}

async fn read_frame<R>(reader: &mut R) -> Result<Value, CdpError>
where
    R: AsyncRead + Unpin,
{
    let mut header = [0_u8; 4];
    reader
        .read_exact(&mut header)
        .await
        .map_err(|error| CdpError::ExtensionBridge(error.to_string()))?;
    let length = u32::from_le_bytes(header) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(CdpError::ExtensionBridge(
            "bridge frame size is outside limits".to_string(),
        ));
    }
    let mut bytes = vec![0_u8; length];
    reader
        .read_exact(&mut bytes)
        .await
        .map_err(|error| CdpError::ExtensionBridge(error.to_string()))?;
    serde_json::from_slice(&bytes).map_err(|error| CdpError::ExtensionBridge(error.to_string()))
}

async fn write_frame<W>(writer: &mut W, message: &Value) -> Result<(), CdpError>
where
    W: AsyncWrite + Unpin,
{
    let bytes = serde_json::to_vec(message)
        .map_err(|error| CdpError::ExtensionBridge(error.to_string()))?;
    if bytes.is_empty() || bytes.len() > MAX_FRAME_BYTES {
        return Err(CdpError::ExtensionBridge(
            "bridge frame size is outside limits".to_string(),
        ));
    }
    let length =
        u32::try_from(bytes.len()).map_err(|error| CdpError::ExtensionBridge(error.to_string()))?;
    writer
        .write_all(&length.to_le_bytes())
        .await
        .map_err(|error| CdpError::ExtensionBridge(error.to_string()))?;
    writer
        .write_all(&bytes)
        .await
        .map_err(|error| CdpError::ExtensionBridge(error.to_string()))?;
    writer
        .flush()
        .await
        .map_err(|error| CdpError::ExtensionBridge(error.to_string()))
}

fn validate_identifier(name: &str, value: &str) -> Result<(), CdpError> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        return Err(CdpError::ExtensionBridge(format!("{name} is invalid")));
    }
    Ok(())
}

fn remove_pending(state: &TransportState, request_id: u64) {
    state
        .pending
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .remove(&request_id);
}

fn fail_pending(state: &TransportState, error: CdpError) {
    let pending = {
        let mut pending = state
            .pending
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        std::mem::take(&mut *pending)
    };
    for (_, sender) in pending {
        let _ = sender.send(Err(error.clone()));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};
    use tokio::net::UnixListener;

    #[tokio::test]
    async fn extension_transport_correlates_commands_and_forwards_events() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock should be after epoch")
            .as_nanos();
        let socket_path = std::env::temp_dir().join(format!("browski-bridge-{unique}.sock"));
        let listener = UnixListener::bind(&socket_path).expect("socket should bind");
        let bridge = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.expect("runtime should connect");
            let (mut reader, mut writer) = stream.into_split();
            let auth = read_frame(&mut reader)
                .await
                .expect("auth frame should parse");
            assert_eq!(auth["role"], "browser_backend");
            assert_eq!(auth["token"], "test-token");
            let hello = read_frame(&mut reader).await.expect("hello should parse");
            assert_eq!(hello["type"], "backend.hello");
            assert_eq!(hello["payload"]["attachmentId"], "attachment-1");
            write_frame(
                &mut writer,
                &json!({
                    "protocolVersion": PROTOCOL_VERSION,
                    "type": "backend.ready",
                }),
            )
            .await
            .expect("ready should be sent");

            let command = read_frame(&mut reader)
                .await
                .expect("command frame should parse");
            assert_eq!(command["type"], "backend.command");
            assert_eq!(command["payload"]["method"], "Page.enable");
            let request_id = command["requestId"].as_u64().expect("request ID");
            write_frame(
                &mut writer,
                &json!({
                    "type": "backend.response",
                    "requestId": request_id,
                    "result": {"enabled": true},
                }),
            )
            .await
            .expect("response should be sent");
            write_frame(
                &mut writer,
                &json!({
                    "type": "backend.event",
                    "method": "Page.loadEventFired",
                    "params": {"timestamp": 42.0},
                }),
            )
            .await
            .expect("event should be sent");
        });

        let transport = ExtensionCdpTransport::connect(
            &socket_path,
            "test-token",
            "attachment-1".to_string(),
            CdpSessionId::from("session-1"),
            Duration::from_secs(2),
        )
        .await
        .expect("transport should negotiate");
        let mut events = transport.subscribe();
        let response = transport
            .command("Page.enable", json!({}))
            .await
            .expect("command should succeed");
        assert_eq!(response["enabled"], true);

        let event = tokio::time::timeout(Duration::from_secs(1), events.recv())
            .await
            .expect("event should arrive")
            .expect("event should be available");
        assert!(matches!(event, CdpEvent::LoadEventFired { .. }));

        transport.close().await;
        bridge.await.expect("bridge task should finish");
        let _ = std::fs::remove_file(socket_path);
    }
}
