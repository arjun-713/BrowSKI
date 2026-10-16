//! First-class runtime errors.
//!
//! Browser crashes and disconnects are *states*: callers match on these
//! variants to choose between bounded mechanical retry (Rust recovery),
//! reattach, and run termination. Anything reaching the Python agent carries
//! the variant plus evidence — never a bare string.

use browser_agent_cdp::{CdpError, FrameId, TargetId};
use std::time::Duration;

/// Errors from the browser runtime.
#[derive(Debug, thiserror::Error)]
pub enum BrowserRuntimeError {
    #[error(transparent)]
    Cdp(#[from] CdpError),
    #[error("browser process exited")]
    BrowserExited,
    #[error("connection to the browser was lost")]
    ConnectionLost,
    #[error("tab's target {0} is closed")]
    TargetClosed(TargetId),
    #[error("frame {0} is detached")]
    FrameDetached(FrameId),
    #[error("cdp command '{method}' timed out after {timeout:?}")]
    CommandTimeout { method: String, timeout: Duration },
    #[error("cdp protocol error {code}: {message}")]
    ProtocolError { code: i64, message: String },
    #[error("failed to launch browser: {0}")]
    LaunchFailure(String),
    #[error("session is closed")]
    SessionClosed,
    #[error("session has no active tab")]
    NoActiveTab,
    #[error("browser returned an invalid response for {method}")]
    InvalidResponse { method: String },
    #[error("navigation to {url} failed: {reason}")]
    NavigationFailed { url: String, reason: String },
}

impl BrowserRuntimeError {
    /// Normalize a [`CdpError`] into the runtime vocabulary, attaching the
    /// active tab/target context where the protocol error is anonymous.
    pub fn from_cdp(err: CdpError, active_target: Option<&TargetId>) -> Self {
        match err {
            CdpError::ConnectionLost | CdpError::WebSocket(_) => {
                BrowserRuntimeError::ConnectionLost
            }
            CdpError::BrowserExited => BrowserRuntimeError::BrowserExited,
            CdpError::Shutdown => BrowserRuntimeError::SessionClosed,
            CdpError::TargetClosed { .. } => match active_target {
                Some(t) => BrowserRuntimeError::TargetClosed(t.clone()),
                None => BrowserRuntimeError::from(CdpError::TargetClosed {
                    target: String::new(),
                }),
            },
            CdpError::CommandTimeout { method, timeout } => {
                BrowserRuntimeError::CommandTimeout { method, timeout }
            }
            CdpError::Protocol { code, message } => {
                BrowserRuntimeError::ProtocolError { code, message }
            }
            other => BrowserRuntimeError::Cdp(other),
        }
    }

    /// True if no further command on this session can succeed.
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            BrowserRuntimeError::BrowserExited
                | BrowserRuntimeError::ConnectionLost
                | BrowserRuntimeError::SessionClosed
        )
    }
}
