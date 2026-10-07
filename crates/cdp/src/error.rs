//! First-class transport and runtime errors.
//!
//! Browser crashes and disconnects are states, not generic failures: callers
//! match on these variants to decide between bounded retry, reattach, and
//! run termination (see `browser-core` recovery mapping).

use std::time::Duration;

/// Errors from the CDP layer.
#[derive(Clone, Debug, thiserror::Error)]
pub enum CdpError {
    #[error("chrome binary not found (set CHROME_PATH or install Chromium/Chrome)")]
    ChromeNotFound,
    #[error("failed to spawn chrome: {0}")]
    Spawn(String),
    #[error("failed to launch browser: {0}")]
    LaunchFailure(String),
    #[error("devtools endpoint did not become ready in time (port {port})")]
    EndpointTimeout { port: u16 },
    #[error("http error: {0}")]
    Http(String),
    #[error("websocket error: {0}")]
    WebSocket(String),
    #[error("extension bridge error: {0}")]
    ExtensionBridge(String),
    #[error("cdp error {code}: {message}")]
    Protocol { code: i64, message: String },
    #[error("no page target available")]
    NoPageTarget,
    #[error("cdp command '{method}' timed out after {timeout:?}")]
    CommandTimeout { method: String, timeout: Duration },
    #[error("navigation/observation timeout after {0:?}")]
    Timeout(Duration),
    #[error("connection to the browser was lost")]
    ConnectionLost,
    #[error("browser process exited")]
    BrowserExited,
    #[error("target {target} is closed")]
    TargetClosed { target: String },
    #[error("frame {frame} is detached")]
    FrameDetached { frame: String },
    #[error("transport is shut down")]
    Shutdown,
    #[error("unexpected cdp response: {0}")]
    Unexpected(String),
}

impl CdpError {
    /// True if the session cannot continue on this transport and must
    /// reconnect (same browser) or terminate the run (browser gone).
    pub fn is_connection_fatal(&self) -> bool {
        matches!(
            self,
            CdpError::ConnectionLost
                | CdpError::BrowserExited
                | CdpError::Shutdown
                | CdpError::WebSocket(_)
        )
    }
}
