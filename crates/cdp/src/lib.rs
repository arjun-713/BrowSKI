//! Typed CDP access, transport, and protocol adapters.
//!
//! Boundary: owns everything Chrome-specific — process launch, the HTTP
//! debugger endpoints, and the persistent multiplexed websocket transport.
//! No agent reasoning, no LLM calls.
//!
//! # Ownership rule
//!
//! **Only a transport implementation owns its connection.** Browser-core
//! uses [`transport::CdpTransport`] for correlated commands and typed events;
//! managed Chromium uses [`transport::PersistentTransport`].

pub mod error;
pub mod event;
pub mod extension;
pub mod http;
pub mod ids;
pub mod launch;
pub mod transport;

pub use error::CdpError;
pub use event::{CdpEvent, FrameSummary, TargetSummary};
pub use extension::ExtensionCdpTransport;
pub use http::{browser_ws_url, close_target_http, list_targets, new_page_target, DebuggerTarget};
pub use ids::{BrowserSessionId, CdpSessionId, ExecutionContextId, FrameId, TabId, TargetId};
pub use launch::{find_chrome_binary, LaunchedChrome};
pub use transport::{CdpTransport, PersistentTransport, DEFAULT_COMMAND_TIMEOUT};
