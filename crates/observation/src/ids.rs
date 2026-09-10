//! Canonical identity newtypes: tabs, targets, frames, sessions, DOM nodes.
//!
//! Distinct types so handles can never be passed interchangeably. The
//! browser state models remain the single home for them (`cdp` and
//! `browser-core` re-export from here).

use serde::{Deserialize, Serialize};

/// Opaque browser session identifier.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct BrowserSessionId(pub String);

/// CDP target identifier (a tab, a background page, a worker, ...).
///
/// Distinct from [`TabId`]: a tab is a *page* target tracked by the session
/// registry; a target is the raw protocol-level entity.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TargetId(pub String);

/// User-visible tab identifier. Wraps the underlying [`TargetId`] value but
/// is a distinct type so tab handles can never be passed where a raw target,
/// frame, or session id is expected.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TabId(pub String);

/// CDP session identifier from `Target.attachToTarget` (flattened mode).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct CdpSessionId(pub String);

/// Frame identifier (CDP frame id).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct FrameId(pub String);

/// CDP backend DOM node id (`DOM.backendNodeId`). Stable across
/// frontend `nodeId` invalidations, but NOT across navigation or
/// re-creation: level-1 reacquisition signal, never the whole identity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct BackendNodeId(pub i64);

/// JS execution-context id (CDP `Runtime.executionContextId`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ExecutionContextId(pub i64);

macro_rules! impl_id {
    ($t:ty) => {
        impl $t {
            pub fn new(id: impl Into<String>) -> Self
            where
                Self: From<String>,
            {
                Self::from(id.into())
            }
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
        impl std::fmt::Display for $t {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                write!(f, "{}", self.0)
            }
        }
        impl From<String> for $t {
            fn from(s: String) -> Self {
                Self(s)
            }
        }
        impl From<&str> for $t {
            fn from(s: &str) -> Self {
                Self(s.to_string())
            }
        }
    };
}

impl_id!(BrowserSessionId);
impl_id!(TargetId);
impl_id!(TabId);
impl_id!(CdpSessionId);
impl_id!(FrameId);

impl BackendNodeId {
    pub fn get(self) -> i64 {
        self.0
    }
}

impl std::fmt::Display for BackendNodeId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "backend:{}", self.0)
    }
}
