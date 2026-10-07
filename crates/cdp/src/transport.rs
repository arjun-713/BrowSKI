//! Persistent multiplexed CDP transport.
//!
//! # Ownership rule
//!
//! **Only this module owns the socket.** Reader and writer tasks are the sole
//! code that touches the WebSocket; every other subsystem talks to the
//! browser through [`PersistentTransport::command`] /
//! [`PersistentTransport::command_in_session`] and the [`CdpEvent`] broadcast
//! bus. Nothing outside this module may hold a socket handle.
//!
//! ```text
//!                    CDP WebSocket
//!                        │
//!               ┌────────┴────────┐
//!               ▼                 ▼
//!           Reader task        Writer task
//!               │                 ▲
//!               │                 │
//!       CDP messages          Command queue (mpsc)
//!               │
//!        ┌──────┴──────┐
//!        ▼             ▼
//!  Responses         Events
//!        │             │
//!  pending map      broadcast bus
//!  (id → oneshot)     │
//!        │        subscribers
//!        ▼
//!  awaiting calls
//! ```
//!
//! Correlation: every command gets an [`AtomicU64`] id; the reader resolves
//! `{"id": N, "result": ...}` against the pending map. Anything without an
//! `id` is an event. Timeouts remove the pending entry, so a slow browser
//! can never deadlock the transport.

use crate::error::CdpError;
use crate::event::CdpEvent;
use crate::ids::CdpSessionId;
use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::{broadcast, mpsc, oneshot};

/// Default per-command timeout.
pub const DEFAULT_COMMAND_TIMEOUT: Duration = Duration::from_secs(30);
const EVENT_CHANNEL_CAPACITY: usize = 1024;
const COMMAND_QUEUE_CAPACITY: usize = 256;

/// Command and event interface consumed by the semantic browser runtime.
///
/// Managed Chromium uses [`PersistentTransport`]. Attached-browser mode can
/// implement the same contract while forwarding commands through the
/// authenticated extension bridge.
pub trait CdpTransport: Send + Sync {
    /// Send a browser-level command and wait for its correlated response.
    fn command<'a>(
        &'a self,
        method: &'a str,
        params: Value,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>>;

    /// Send a command to an attached target session.
    fn command_in_session<'a>(
        &'a self,
        session: &'a CdpSessionId,
        method: &'a str,
        params: Value,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>>;

    /// Send a command with a caller-selected deadline.
    fn command_with_timeout<'a>(
        &'a self,
        session: Option<&'a CdpSessionId>,
        method: &'a str,
        params: Value,
        timeout: Duration,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>>;

    /// Subscribe to protocol events.
    fn subscribe(&self) -> broadcast::Receiver<CdpEvent>;

    /// Report whether the transport is usable.
    fn is_connected(&self) -> bool;

    /// Return the number of command responses currently pending.
    fn pending_commands(&self) -> usize;

    /// Close the transport and stop its owned background tasks.
    fn close<'a>(&'a self) -> Pin<Box<dyn Future<Output = ()> + Send + 'a>>;
}

struct Outbound {
    id: u64,
    session: Option<String>,
    method: String,
    params: Value,
}

fn debug_wire(dir: &str, text: &str) {
    if std::env::var("BROWSER_AGENT_WIRE").is_ok() {
        let short: String = text.chars().take(500).collect();
        eprintln!("[wire {dir}] {short}");
    }
}

struct TransportState {
    pending: Mutex<HashMap<u64, oneshot::Sender<Result<Value, CdpError>>>>,
    connected: AtomicBool,
}

/// Fail every pending command and announce the outage. Idempotent: the first
/// caller flips `connected` and does the work; later callers are no-ops.
fn fail_connection(
    state: &Arc<TransportState>,
    event_tx: &broadcast::Sender<CdpEvent>,
    reason: CdpError,
) {
    if state
        .connected
        .compare_exchange(true, false, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return;
    }
    let pending = std::mem::take(&mut *state.pending.lock().unwrap_or_else(|e| e.into_inner()));
    // fns below only need Debug; CdpError is Debug but not Clone, so rebuild
    // a ConnectionLost for each waiter (all connection failures surface alike).
    let _ = &reason;
    for (_, tx) in pending {
        let _ = tx.send(Err(CdpError::ConnectionLost));
    }
    let _ = event_tx.send(CdpEvent::ConnectionLost);
}

/// One persistent browser-level CDP connection.
///
/// Connect to the **browser** endpoint (`/json/version`'s
/// `webSocketDebuggerUrl`); target-scoped commands go through
/// [`PersistentTransport::command_in_session`] with flattened session ids.
pub struct PersistentTransport {
    id_alloc: AtomicU64,
    state: Arc<TransportState>,
    cmd_tx: mpsc::Sender<Outbound>,
    event_tx: broadcast::Sender<CdpEvent>,
    command_timeout: Duration,
    tasks: Mutex<Vec<tokio::task::JoinHandle<()>>>,
    closed: AtomicBool,
}

impl PersistentTransport {
    /// Open the connection and spawn reader/writer tasks.
    pub async fn connect(
        browser_ws_url: &str,
        command_timeout: Duration,
    ) -> Result<Self, CdpError> {
        let (ws, _) = tokio_tungstenite::connect_async(browser_ws_url)
            .await
            .map_err(|e| CdpError::WebSocket(e.to_string()))?;
        let (sink, stream) = ws.split();

        let state = Arc::new(TransportState {
            pending: Mutex::new(HashMap::new()),
            connected: AtomicBool::new(true),
        });
        let (cmd_tx, cmd_rx) = mpsc::channel(COMMAND_QUEUE_CAPACITY);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);

        let reader = tokio::spawn(reader_task(stream, Arc::clone(&state), event_tx.clone()));
        let writer = tokio::spawn(writer_task(
            sink,
            cmd_rx,
            Arc::clone(&state),
            event_tx.clone(),
        ));

        Ok(Self {
            id_alloc: AtomicU64::new(1),
            state,
            cmd_tx,
            event_tx,
            command_timeout,
            tasks: Mutex::new(vec![reader, writer]),
            closed: AtomicBool::new(false),
        })
    }

    /// Browser-level command (no session).
    pub async fn command(&self, method: &str, params: Value) -> Result<Value, CdpError> {
        self.command_inner(None, method, params, self.command_timeout)
            .await
    }

    /// Target-scoped command on a flattened session.
    pub async fn command_in_session(
        &self,
        session: &CdpSessionId,
        method: &str,
        params: Value,
    ) -> Result<Value, CdpError> {
        self.command_inner(Some(session), method, params, self.command_timeout)
            .await
    }

    /// Command with an explicit timeout (tests, watchdogs).
    pub async fn command_with_timeout(
        &self,
        session: Option<&CdpSessionId>,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, CdpError> {
        self.command_inner(session, method, params, timeout).await
    }

    async fn command_inner(
        &self,
        session: Option<&CdpSessionId>,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, CdpError> {
        if self.closed.load(Ordering::SeqCst) {
            return Err(CdpError::Shutdown);
        }
        if !self.state.connected.load(Ordering::SeqCst) {
            return Err(CdpError::ConnectionLost);
        }
        let id = self.id_alloc.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        self.state
            .pending
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(id, tx);
        let out = Outbound {
            id,
            session: session.map(|s| s.as_str().to_string()),
            method: method.to_string(),
            params,
        };
        if self.cmd_tx.send(out).await.is_err() {
            self.state
                .pending
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(&id);
            return Err(CdpError::ConnectionLost);
        }
        match tokio::time::timeout(timeout, rx).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err(CdpError::ConnectionLost), // sender dropped: transport died
            Err(_) => {
                // Timeout: drop the entry so a late response cannot resolve a
                // recycled waiter (ids are never recycled, but the map must
                // not grow). No deadlock by construction.
                self.state
                    .pending
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .remove(&id);
                Err(CdpError::CommandTimeout {
                    method: method.to_string(),
                    timeout,
                })
            }
        }
    }

    /// Subscribe to the typed event bus.
    pub fn subscribe(&self) -> broadcast::Receiver<CdpEvent> {
        self.event_tx.subscribe()
    }

    pub fn is_connected(&self) -> bool {
        !self.closed.load(Ordering::SeqCst) && self.state.connected.load(Ordering::SeqCst)
    }

    /// Number of commands currently awaiting a response (leak watchdog).
    pub fn pending_commands(&self) -> usize {
        self.state.pending.lock().map(|g| g.len()).unwrap_or(0)
    }

    /// Graceful shutdown: fail pending work with [`CdpError::Shutdown`] and
    /// stop the background tasks. Idempotent.
    pub async fn close(&self) {
        if self.closed.swap(true, Ordering::SeqCst) {
            return;
        }
        self.state.connected.store(false, Ordering::SeqCst);
        let pending =
            std::mem::take(&mut *self.state.pending.lock().unwrap_or_else(|e| e.into_inner()));
        for (_, tx) in pending {
            let _ = tx.send(Err(CdpError::Shutdown));
        }
        let handles = std::mem::take(&mut *self.tasks.lock().unwrap_or_else(|e| e.into_inner()));
        for h in handles {
            h.abort();
        }
    }
}

impl CdpTransport for PersistentTransport {
    fn command<'a>(
        &'a self,
        method: &'a str,
        params: Value,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
        Box::pin(PersistentTransport::command(self, method, params))
    }

    fn command_in_session<'a>(
        &'a self,
        session: &'a CdpSessionId,
        method: &'a str,
        params: Value,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
        Box::pin(PersistentTransport::command_in_session(
            self, session, method, params,
        ))
    }

    fn command_with_timeout<'a>(
        &'a self,
        session: Option<&'a CdpSessionId>,
        method: &'a str,
        params: Value,
        timeout: Duration,
    ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
        Box::pin(PersistentTransport::command_with_timeout(
            self, session, method, params, timeout,
        ))
    }

    fn subscribe(&self) -> broadcast::Receiver<CdpEvent> {
        PersistentTransport::subscribe(self)
    }

    fn is_connected(&self) -> bool {
        PersistentTransport::is_connected(self)
    }

    fn pending_commands(&self) -> usize {
        PersistentTransport::pending_commands(self)
    }

    fn close<'a>(&'a self) -> Pin<Box<dyn Future<Output = ()> + Send + 'a>> {
        Box::pin(PersistentTransport::close(self))
    }
}

impl Drop for PersistentTransport {
    fn drop(&mut self) {
        self.closed.store(true, Ordering::SeqCst);
        self.state.connected.store(false, Ordering::SeqCst);
        if let Ok(mut tasks) = self.tasks.lock() {
            for h in tasks.drain(..) {
                h.abort();
            }
        }
    }
}

async fn reader_task<S>(
    mut stream: S,
    state: Arc<TransportState>,
    event_tx: broadcast::Sender<CdpEvent>,
) where
    S: StreamExt<
            Item = Result<
                tokio_tungstenite::tungstenite::Message,
                tokio_tungstenite::tungstenite::Error,
            >,
        > + Unpin,
{
    while let Some(msg) = stream.next().await {
        let text = match msg {
            Ok(tokio_tungstenite::tungstenite::Message::Text(t)) => t.to_string(),
            Ok(tokio_tungstenite::tungstenite::Message::Close(_)) => break,
            Ok(_) => continue,
            Err(_) => break,
        };
        let v: Value = match serde_json::from_str(&text) {
            Ok(v) => v,
            Err(_) => continue, // never let a malformed frame kill the reader
        };
        debug_wire("<<", &text);
        if let Some(id) = v.get("id").and_then(Value::as_u64) {
            let tx = state
                .pending
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(&id);
            if let Some(tx) = tx {
                let result = match v.get("error") {
                    Some(err) => Err(CdpError::Protocol {
                        code: err.get("code").and_then(Value::as_i64).unwrap_or(-1),
                        message: err
                            .get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("unknown")
                            .to_string(),
                    }),
                    None => Ok(v.get("result").cloned().unwrap_or(Value::Null)),
                };
                let _ = tx.send(result);
            } else {
                tracing::debug!("cdp response for unknown/timed-out id {id}");
            }
        } else if v.get("method").is_some() {
            // Events must never block the reader: lagged subscribers drop.
            let _ = event_tx.send(CdpEvent::parse(&v));
        }
    }
    fail_connection(&state, &event_tx, CdpError::ConnectionLost);
}

async fn writer_task<S>(
    mut sink: S,
    mut cmd_rx: mpsc::Receiver<Outbound>,
    state: Arc<TransportState>,
    event_tx: broadcast::Sender<CdpEvent>,
) where
    S: SinkExt<
            tokio_tungstenite::tungstenite::Message,
            Error = tokio_tungstenite::tungstenite::Error,
        > + Unpin,
{
    while let Some(out) = cmd_rx.recv().await {
        let mut req = serde_json::json!({
            "id": out.id,
            "method": out.method,
            "params": out.params,
        });
        if let Some(session) = out.session {
            req["sessionId"] = Value::from(session);
        }
        let text = req.to_string();
        debug_wire(">>", &text);
        if sink
            .send(tokio_tungstenite::tungstenite::Message::Text(text.into()))
            .await
            .is_err()
        {
            break;
        }
    }
    fail_connection(&state, &event_tx, CdpError::ConnectionLost);
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;

    /// Fake CDP server: answers `Echo.ping` with the same id, emits one
    /// event, then answers nothing (for timeout tests, use `blackhole`).
    async fn fake_server(addr_tx: oneshot::Sender<String>, blackhole: bool) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let _ = addr_tx.send(format!("ws://{}/devtools", listener.local_addr().unwrap()));
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        if !blackhole {
            // Emit an event first (no id).
            ws.send(tokio_tungstenite::tungstenite::Message::Text(
                r#"{"method":"Page.loadEventFired","params":{"timestamp":1.0}}"#.into(),
            ))
            .await
            .unwrap();
            // Answer every command with its own id.
            while let Some(Ok(msg)) = ws.next().await {
                if let tokio_tungstenite::tungstenite::Message::Text(t) = msg {
                    let v: Value = serde_json::from_str(&t).unwrap();
                    let id = v["id"].clone();
                    ws.send(tokio_tungstenite::tungstenite::Message::Text(
                        serde_json::json!({"id": id, "result": {"echo": true}})
                            .to_string()
                            .into(),
                    ))
                    .await
                    .unwrap();
                }
            }
        } else {
            // Accept and never respond.
            while ws.next().await.is_some() {}
        }
    }

    #[tokio::test]
    async fn commands_correlate_and_events_flow() {
        let (tx, rx) = oneshot::channel();
        tokio::spawn(fake_server(tx, false));
        let url = rx.await.unwrap();
        let t = std::sync::Arc::new(
            PersistentTransport::connect(&url, Duration::from_secs(5))
                .await
                .unwrap(),
        );
        let mut events = t.subscribe();

        // Event emitted before any command must be receivable.
        let ev = tokio::time::timeout(Duration::from_secs(5), events.recv())
            .await
            .unwrap()
            .unwrap();
        assert!(matches!(ev, CdpEvent::LoadEventFired { .. }));

        // Concurrent commands resolve against their own ids.
        let mut handles = Vec::new();
        for _ in 0..20 {
            let t = std::sync::Arc::clone(&t);
            handles.push(tokio::spawn(async move {
                t.command("Echo.ping", Value::Null).await
            }));
        }
        for h in handles {
            let r = h.await.unwrap().unwrap();
            assert_eq!(r, serde_json::json!({"echo": true}));
        }
        assert_eq!(t.pending_commands(), 0);
        t.close().await;
    }

    #[tokio::test]
    async fn command_timeout_does_not_deadlock() {
        let (tx, rx) = oneshot::channel();
        tokio::spawn(fake_server(tx, true));
        let url = rx.await.unwrap();
        let t = PersistentTransport::connect(&url, Duration::from_secs(5))
            .await
            .unwrap();
        let err = t
            .command_with_timeout(None, "Echo.ping", Value::Null, Duration::from_millis(200))
            .await
            .unwrap_err();
        assert!(matches!(err, CdpError::CommandTimeout { .. }));
        assert_eq!(t.pending_commands(), 0);
        // The transport stays usable: a second command also times out
        // cleanly instead of deadlocking behind the first.
        let err2 = t
            .command_with_timeout(None, "Echo.ping", Value::Null, Duration::from_millis(200))
            .await
            .unwrap_err();
        assert!(matches!(err2, CdpError::CommandTimeout { .. }));
        assert_eq!(t.pending_commands(), 0);
        t.close().await;
    }

    #[tokio::test]
    async fn server_close_surfaces_connection_lost() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("ws://{}/x", listener.local_addr().unwrap());
        let accept = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            ws.close(None).await.unwrap();
        });
        let t = PersistentTransport::connect(&url, Duration::from_secs(5))
            .await
            .unwrap();
        let mut events = t.subscribe();
        // Reader observes the close; event or command failure must follow.
        let ev = tokio::time::timeout(Duration::from_secs(5), events.recv())
            .await
            .unwrap()
            .unwrap();
        assert!(matches!(ev, CdpEvent::ConnectionLost));
        let err = t.command("Echo.ping", Value::Null).await.unwrap_err();
        assert!(matches!(err, CdpError::ConnectionLost));
        let _ = accept.await;
    }
}
