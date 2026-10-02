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

pub mod act;
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
// Executor surface re-exported for agent-layer consumers (single hop).
pub use browser_agent_executor::{
    ActOptions, ActionOutcome, BrowserAction, ExecutionFailure, ExecutionFailureKind,
};
pub use browser_agent_verification::{SideEffects, VerificationResult};

/// Test/support helper: default side effects (no events observed).
pub fn verification_side_effects() -> SideEffects {
    SideEffects::default()
}

/// Test/support helper: pure verification entry point.
pub fn verify_for_test(
    expected: &browser_agent_verification::ExpectedEffect,
    action_type: &str,
    before: &SemanticSnapshot,
    after: &SemanticSnapshot,
    delta: &SnapshotDelta,
    side: &SideEffects,
) -> VerificationResult {
    browser_agent_verification::verify_expected(expected, action_type, before, after, delta, side)
}
