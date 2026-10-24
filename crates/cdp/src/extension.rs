//! Authenticated Unix-socket transport for the Chrome extension debugger proxy.

use crate::error::CdpError;
use crate::event::CdpEvent;
use crate::ids::{CdpSessionId, TargetId};
use crate::transport::{CdpTransport, OwnedTab};
use serde::Deserialize;
use serde_json::{json, Value};
use serde_stacker::Deserializer as StackSafeDeserializer;
use std::collections::HashMap;
use std::future::Future;
use std::path::Path;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::UnixStream;
use tokio::sync::{broadcast, mpsc, oneshot};
use tokio::task::JoinHandle;

const PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 8 * 1024 * 1024;
const MAX_JSON_DEPTH: usize = 256;
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
    owned_sessions: Mutex<HashMap<String, String>>,
}

/// CDP transport pinned to one user-confirmed extension tab attachment.
///
/// The Python bridge owns Native Messaging and forwards only versioned,
/// authenticated messages to this Unix socket. This transport never listens
/// on a network interface and never changes its attachment target.
pub struct ExtensionCdpTransport {
    attachment_id: String,
    session_id: CdpSessionId,
    next_request_id: Mutex<u64>,
    command_timeout: Duration,
    owned_popups: bool,
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
            owned_sessions: Mutex::new(HashMap::new()),
        });
        let reader_task = tokio::spawn(reader_task(reader, Arc::clone(&state), event_tx.clone()));
        let writer_task = tokio::spawn(writer_task(writer, command_rx, Arc::clone(&state)));

        Ok(Self {
            attachment_id,
            session_id,
            next_request_id: Mutex::new(1),
            command_timeout,
            owned_popups: ready
                .get("ownedPopups")
                .and_then(Value::as_bool)
                .unwrap_or(false),
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
        let target_session_id = session
            .map(CdpSessionId::as_str)
            .unwrap_or_else(|| self.session_id.as_str());
        if target_session_id != self.session_id.as_str()
            && !self
                .state
                .owned_sessions
                .lock()
                .unwrap_or_else(|error| error.into_inner())
                .contains_key(target_session_id)
        {
            return Err(CdpError::ExtensionBridge(
                "command session is not owned by this extension attachment".to_string(),
            ));
        }

        // Reserve capacity before acquiring any synchronous locks. Assign the
        // wire ID and enqueue together so concurrent callers cannot arrive out
        // of order at the bridge's replay-protected receiver.
        let permit = self
            .command_tx
            .reserve()
            .await
            .map_err(|_| CdpError::ConnectionLost)?;
        let (sender, receiver) = oneshot::channel();
        let request_id = {
            let mut next = self
                .next_request_id
                .lock()
                .unwrap_or_else(|error| error.into_inner());
            let request_id = *next;
            *next += 1;
            self.state
                .pending
                .lock()
                .unwrap_or_else(|error| error.into_inner())
                .insert(request_id, sender);
            permit.send(OutboundCommand {
                request_id,
                attachment_id: self.attachment_id.clone(),
                session_id: target_session_id.to_string(),
                method: method.to_string(),
                params,
            });
            request_id
        };

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

    fn remember_owned_tab(&self, tab: &OwnedTab) -> Result<(), CdpError> {
        validate_identifier("owned target ID", tab.target.as_str())?;
        validate_identifier("owned tab session ID", tab.session.as_str())?;
        if tab.session == self.session_id {
            return Err(CdpError::ExtensionBridge(
                "owned tab session ID collides with the root attachment".to_string(),
            ));
        }
        self.state
            .owned_sessions
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .insert(
                tab.session.as_str().to_string(),
                tab.target.as_str().to_string(),
            );
        Ok(())
    }

    fn parse_owned_tab(&self, value: Value) -> Result<OwnedTab, CdpError> {
        let target = value
            .get("targetId")
            .and_then(Value::as_str)
            .ok_or_else(|| CdpError::Unexpected("owned tab response has no target ID".into()))?;
        let session = value
            .get("tabSessionId")
            .and_then(Value::as_str)
            .ok_or_else(|| CdpError::Unexpected("owned tab response has no session ID".into()))?;
        let title = value
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let url = value
            .get("url")
            .and_then(Value::as_str)
            .ok_or_else(|| CdpError::Unexpected("owned tab response has no URL".into()))?
            .to_string();
        let tab = OwnedTab {
            target: TargetId::from(target.to_string()),
            session: CdpSessionId::from(session.to_string()),
            title,
            url,
        };
        self.remember_owned_tab(&tab)?;
        Ok(tab)
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

    fn create_owned_tab<'a>(
        &'a self,
        url: &'a str,
    ) -> Pin<Box<dyn Future<Output = Result<OwnedTab, CdpError>> + Send + 'a>> {
        Box::pin(async move {
            let result = self
                .command_inner(
                    None,
                    "BROWSKI.tabs.create",
                    json!({ "url": url }),
                    self.command_timeout,
                )
                .await?;
            self.parse_owned_tab(result)
        })
    }

    fn supports_owned_popups(&self) -> bool {
        self.owned_popups
    }

    fn prepare_owned_popup<'a>(
        &'a self,
        opener: &'a CdpSessionId,
        url: &'a str,
    ) -> Pin<Box<dyn Future<Output = Result<String, CdpError>> + Send + 'a>> {
        Box::pin(async move {
            let result = self
                .command_inner(
                    None,
                    "BROWSKI.tabs.preparePopup",
                    json!({"openerSessionId": opener.as_str(), "url": url}),
                    self.command_timeout,
                )
                .await?;
            let id = result
                .get("popupId")
                .and_then(Value::as_str)
                .ok_or_else(|| CdpError::Unexpected("popup expectation has no identity".into()))?;
            validate_identifier("popup identity", id)?;
            Ok(id.to_owned())
        })
    }

    fn finish_owned_popup<'a>(
        &'a self,
        popup_id: &'a str,
        cancel: bool,
    ) -> Pin<Box<dyn Future<Output = Result<Option<OwnedTab>, CdpError>> + Send + 'a>> {
        Box::pin(async move {
            let result = self
                .command_inner(
                    None,
                    "BROWSKI.tabs.finishPopup",
                    json!({"popupId": popup_id, "cancel": cancel}),
                    self.command_timeout,
                )
                .await?;
            if cancel {
                return Ok(None);
            }
            self.parse_owned_tab(result).map(Some)
        })
    }

    fn activate_owned_tab<'a>(
        &'a self,
        target: &'a TargetId,
    ) -> Pin<Box<dyn Future<Output = Result<(), CdpError>> + Send + 'a>> {
        Box::pin(async move {
            self.command_inner(
                None,
                "BROWSKI.tabs.activate",
                json!({ "targetId": target.as_str() }),
                self.command_timeout,
            )
            .await?;
            Ok(())
        })
    }

    fn close_owned_tab<'a>(
        &'a self,
        target: &'a TargetId,
    ) -> Pin<Box<dyn Future<Output = Result<(), CdpError>> + Send + 'a>> {
        Box::pin(async move {
            self.command_inner(
                None,
                "BROWSKI.tabs.close",
                json!({ "targetId": target.as_str() }),
                self.command_timeout,
            )
            .await?;
            Ok(())
        })
    }

    fn detach_owned_tabs<'a>(
        &'a self,
    ) -> Pin<Box<dyn Future<Output = Result<(), CdpError>> + Send + 'a>> {
        Box::pin(async move {
            self.command_inner(None, "BROWSKI.tabs.stop", json!({}), self.command_timeout)
                .await?;
            Ok(())
        })
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
    let disconnect_error = loop {
        let message = match read_frame(&mut reader).await {
            Ok(message) => message,
            Err(error) => break error,
        };
        let message_type = message
            .get("type")
            .and_then(Value::as_str)
            .map(str::to_owned);
        match message_type.as_deref() {
            Some("backend.response") => handle_response(&state, message),
            Some("backend.event") => handle_event(&event_tx, &state, &message),
            _ => break CdpError::ConnectionLost,
        }
    };
    state.connected.store(false, Ordering::SeqCst);
    fail_pending(&state, disconnect_error);
    let _ = event_tx.send(CdpEvent::ConnectionLost);
}

fn handle_response(state: &TransportState, mut message: Value) {
    let Some(request_id) = message.get("requestId").and_then(Value::as_u64) else {
        return;
    };
    let sender = state
        .pending
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .remove(&request_id);
    if let Some(sender) = sender {
        let result = if let Some(result) = message.get_mut("result") {
            Ok(std::mem::take(result))
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

fn handle_event(event_tx: &broadcast::Sender<CdpEvent>, state: &TransportState, message: &Value) {
    let Some(method) = message.get("method").and_then(Value::as_str) else {
        return;
    };
    if method == "Target.targetDestroyed" {
        if let Some(target_id) = message
            .get("params")
            .and_then(|params| params.get("targetId"))
            .and_then(Value::as_str)
        {
            state
                .owned_sessions
                .lock()
                .unwrap_or_else(|error| error.into_inner())
                .retain(|_, owned_target| owned_target != target_id);
        }
    }
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
        .map_err(|_| CdpError::ExtensionBridge("extension bridge frame read failed".into()))?;
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
        .map_err(|_| CdpError::ExtensionBridge("extension bridge frame read failed".into()))?;
    ensure_json_depth_within_limit(&bytes)?;

    let mut deserializer = serde_json::Deserializer::from_slice(&bytes);
    deserializer.disable_recursion_limit();
    let stack_safe = StackSafeDeserializer::new(&mut deserializer);
    let value = Value::deserialize(stack_safe).map_err(safe_frame_parse_error)?;
    deserializer.end().map_err(safe_frame_parse_error)?;
    Ok(value)
}

fn ensure_json_depth_within_limit(bytes: &[u8]) -> Result<(), CdpError> {
    let mut depth = 0_usize;
    let mut inside_string = false;
    let mut escaped = false;

    for byte in bytes {
        if inside_string {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                inside_string = false;
            }
            continue;
        }

        match *byte {
            b'"' => inside_string = true,
            b'{' | b'[' => {
                depth += 1;
                if depth > MAX_JSON_DEPTH {
                    return Err(frame_depth_error());
                }
            }
            b'}' | b']' => depth = depth.saturating_sub(1),
            _ => {}
        }
    }

    Ok(())
}

fn frame_depth_error() -> CdpError {
    CdpError::ExtensionBridge("recursion limit exceeded".into())
}

fn safe_frame_parse_error(error: serde_json::Error) -> CdpError {
    if error.to_string().contains("recursion limit exceeded") {
        return CdpError::ExtensionBridge("recursion limit exceeded".into());
    }
    CdpError::ExtensionBridge("invalid extension bridge JSON frame".into())
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
    use tokio::net::{UnixListener, UnixStream};

    async fn pending_result_for_frame(payload: &[u8]) -> Result<Value, CdpError> {
        let (mut writer, stream) = UnixStream::pair().expect("socket pair should be created");
        let (reader, _reader_writer) = stream.into_split();
        let state = Arc::new(TransportState {
            connected: AtomicBool::new(true),
            pending: Mutex::new(HashMap::new()),
            owned_sessions: Mutex::new(HashMap::new()),
        });
        let (pending_sender, pending_receiver) = oneshot::channel();
        state
            .pending
            .lock()
            .expect("pending lock")
            .insert(7, pending_sender);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);
        let reader_task = tokio::spawn(reader_task(reader, Arc::clone(&state), event_tx));

        let mut frame = Vec::with_capacity(payload.len() + 4);
        frame.extend_from_slice(
            &u32::try_from(payload.len())
                .expect("test frame length fits in u32")
                .to_le_bytes(),
        );
        frame.extend_from_slice(payload);
        writer
            .write_all(&frame)
            .await
            .expect("test frame should be written");
        drop(writer);

        reader_task.await.expect("reader task should finish");
        pending_receiver
            .await
            .expect("pending command should receive disconnect")
    }

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

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn concurrent_commands_enqueue_monotonic_request_ids() {
        let state = Arc::new(TransportState {
            connected: AtomicBool::new(true),
            pending: Mutex::new(HashMap::new()),
            owned_sessions: Mutex::new(HashMap::new()),
        });
        let (command_tx, mut command_rx) = mpsc::channel(COMMAND_QUEUE_CAPACITY);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);
        let transport = Arc::new(ExtensionCdpTransport {
            owned_popups: false,
            attachment_id: "attachment-1".into(),
            session_id: CdpSessionId::from("session-1"),
            next_request_id: Mutex::new(1),
            command_timeout: Duration::from_secs(5),
            state: Arc::clone(&state),
            command_tx,
            event_tx,
            tasks: Mutex::new(Vec::new()),
        });
        let receiver = tokio::spawn(async move {
            for expected_id in 1..=512 {
                let command = command_rx.recv().await.expect("command should arrive");
                assert_eq!(command.request_id, expected_id);
                let sender = state
                    .pending
                    .lock()
                    .expect("pending lock")
                    .remove(&expected_id)
                    .expect("command should be registered");
                sender
                    .send(Ok(json!({})))
                    .expect("caller should remain available");
            }
        });
        let mut callers = Vec::new();
        for _ in 0..512 {
            let transport = Arc::clone(&transport);
            callers.push(tokio::spawn(async move {
                transport
                    .command("Page.enable", json!({}))
                    .await
                    .expect("command should succeed");
            }));
        }
        for caller in callers {
            caller.await.expect("caller should finish");
        }
        receiver.await.expect("receiver should finish");
        assert_eq!(transport.pending_commands(), 0);
    }

    #[tokio::test]
    async fn malformed_frame_propagates_safe_error_to_pending_command() {
        let payload = br#"{"private":"PAGE_CONTENT""#;

        let error = pending_result_for_frame(payload)
            .await
            .expect_err("malformed frame should fail the pending command");

        assert!(matches!(
            &error,
            CdpError::ExtensionBridge(message)
                if message == "invalid extension bridge JSON frame"
        ));
        assert!(!error.to_string().contains("PAGE_CONTENT"));
    }

    #[tokio::test]
    async fn trailing_json_content_is_rejected_without_echoing_payload() {
        let payload =
            br#"{"type":"backend.response","requestId":7,"result":{}}{"private":"PAGE_CONTENT"}"#;

        let error = pending_result_for_frame(payload)
            .await
            .expect_err("trailing JSON content should be rejected");

        assert!(matches!(
            &error,
            CdpError::ExtensionBridge(message)
                if message == "invalid extension bridge JSON frame"
        ));
        assert!(!error.to_string().contains("PAGE_CONTENT"));
    }

    #[tokio::test]
    async fn deep_frame_propagates_safe_depth_error_to_pending_command() {
        let depth = MAX_JSON_DEPTH + 1;
        let nested = format!("{}0{}", "[".repeat(depth), "]".repeat(depth));
        let payload = format!(r#"{{"type":"backend.response","requestId":7,"result":{nested}}}"#);

        let error = pending_result_for_frame(payload.as_bytes())
            .await
            .expect_err("overly deep frame should fail the pending command");

        assert!(matches!(
            &error,
            CdpError::ExtensionBridge(message) if message == "recursion limit exceeded"
        ));
        assert!(error.to_string().len() < 128);
    }

    #[tokio::test]
    async fn bounded_deep_dom_response_reaches_pending_command() {
        let depth = 171;
        let nested = format!("{}0{}", "[".repeat(depth), "]".repeat(depth));
        let payload =
            format!(r#"{{"type":"backend.response","requestId":7,"result":{{"dom":{nested}}}}}"#);

        let result = pending_result_for_frame(payload.as_bytes())
            .await
            .expect("bounded deep response should parse and reach caller");
        let mut value = &result["dom"];
        let mut parsed_depth = 0;
        while let Value::Array(items) = value {
            parsed_depth += 1;
            value = &items[0];
        }

        assert_eq!(parsed_depth, depth);
        assert_eq!(value, &Value::from(0));
    }

    #[tokio::test]
    async fn bracket_characters_in_escaped_strings_do_not_count_as_depth() {
        let text = "[\\\"{".repeat(MAX_JSON_DEPTH);
        let payload = json!({
            "type": "backend.response",
            "requestId": 7,
            "result": { "text": text },
        })
        .to_string();

        let result = pending_result_for_frame(payload.as_bytes())
            .await
            .expect("escaped brackets in strings should not count as nesting");

        assert_eq!(result["text"], text);
    }
}
