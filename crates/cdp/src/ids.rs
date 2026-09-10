//! Canonical protocol identity types (re-exported from `observation`).
//!
//! Tab ids, target ids, frame ids, and CDP session ids are distinct newtypes
//! so they can never be passed interchangeably. See `observation` for the
//! definitions; the browser state models remain the single home for them.

pub use browser_agent_observation::{
    BrowserSessionId, CdpSessionId, ExecutionContextId, FrameId, TabId, TargetId,
};
