//! Central browser runtime API: `BrowserSession` lifecycle, tab/frame
//! coordination, browser events.
//!
//! Boundary: owns live browser sessions (Chromium process + persistent CDP
//! transport + tab/frame registry + typed event bus). Delegates transport to
//! `cdp`, state shapes to `observation`, identity to `element-registry`,
//! verification to `verification`, and low-level retries to `recovery`.
//! Contains no LLM calls and knows nothing about providers.
//!
//! Browser state is never trusted indefinitely: every [`BrowserSession`]
//! carries a monotonically increasing `generation` bumped on navigation so
//! stale [`ElementRef`](browser_agent_element_registry::ElementRef)s can be
//! detected, and the [`TabRegistry`](model::TabRegistry) is rebuilt from
//! transport events rather than cached forever.

pub mod error;
pub mod events;
pub mod model;
pub mod observer;
pub mod session;

pub use error::BrowserRuntimeError;
pub use events::BrowserEvent;
pub use model::{Tab, TabRegistry};
pub use session::{BrowserSession, LaunchOptions, TabInfo};
// Observation surface re-exported for agent-layer consumers (single hop).
pub use browser_agent_observation::{
    AgentObservation, SemanticElement, SemanticSnapshot, SnapshotDelta, TabId, TargetId,
    VisibilityClass,
};
