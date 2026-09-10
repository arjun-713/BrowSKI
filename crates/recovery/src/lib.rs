//! Low-level recoverable browser failures and bounded mechanical retries.
//!
//! Boundary: mechanical recovery only (stale nodes, detached frames,
//! intercepted actions, navigation races). Strategy changes / replanning
//! belong to the Python agent runtime (`python/src/browser_agent/recovery`).
//! Retries are ALWAYS bounded.

use serde::{Deserialize, Serialize};

/// Maximum mechanical retries for any single low-level operation.
pub const MAX_MECHANICAL_RETRIES: u32 = 3;

/// Structured low-level failure kinds owned by the Rust browser core.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum FailureKind {
    StaleNode,
    DetachedFrame,
    InterceptedAction,
    NavigationRace,
    Timeout,
    TargetGone,
    ProtocolError,
    Unknown,
}

/// What the low-level recovery subsystem decided.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "decision", rename_all = "snake_case")]
pub enum RecoveryDecision {
    /// Retry the same mechanical step; `attempt` is 1-based.
    Retry { attempt: u32, max_attempts: u32 },
    /// Reacquire state (fresh snapshot) then retry.
    ReacquireAndRetry { attempt: u32, max_attempts: u32 },
    /// Give up at this level; escalate to the Python agent with evidence.
    Escalate { reason: String },
}

impl RecoveryDecision {
    /// Bounded retry policy: retries while `attempt < max_attempts`.
    pub fn bounded_retry(attempt: u32, max_attempts: u32, kind: FailureKind) -> Self {
        if attempt < max_attempts {
            match kind {
                FailureKind::StaleNode | FailureKind::DetachedFrame => {
                    RecoveryDecision::ReacquireAndRetry {
                        attempt: attempt + 1,
                        max_attempts,
                    }
                }
                _ => RecoveryDecision::Retry {
                    attempt: attempt + 1,
                    max_attempts,
                },
            }
        } else {
            RecoveryDecision::Escalate {
                reason: format!("{kind:?} persisted after {max_attempts} attempts"),
            }
        }
    }
}

/// Classify a CDP/transport error string into a [`FailureKind`]. Best-effort
/// string matching for the slice; the typed protocol layer will refine this.
pub fn classify_error(message: &str) -> FailureKind {
    let m = message.to_lowercase();
    if m.contains("stale") || m.contains("no node with given id") {
        FailureKind::StaleNode
    } else if m.contains("detached") || m.contains("frame") && m.contains("not found") {
        FailureKind::DetachedFrame
    } else if m.contains("intercept") || m.contains("not clickable") || m.contains("obscures") {
        FailureKind::InterceptedAction
    } else if m.contains("navigation") || m.contains("renderer") && m.contains("navigat") {
        FailureKind::NavigationRace
    } else if m.contains("timeout") || m.contains("timed out") {
        FailureKind::Timeout
    } else if m.contains("target")
        && (m.contains("gone") || m.contains("closed") || m.contains("crashed"))
    {
        FailureKind::TargetGone
    } else if m.contains("protocol") || m.contains("cdp") || m.contains("websocket") {
        FailureKind::ProtocolError
    } else {
        FailureKind::Unknown
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retries_are_bounded() {
        let d = RecoveryDecision::bounded_retry(3, MAX_MECHANICAL_RETRIES, FailureKind::Timeout);
        assert!(matches!(d, RecoveryDecision::Escalate { .. }));
        let d = RecoveryDecision::bounded_retry(0, MAX_MECHANICAL_RETRIES, FailureKind::Timeout);
        assert!(matches!(d, RecoveryDecision::Retry { .. }));
    }

    #[test]
    fn stale_nodes_trigger_reacquire() {
        let d = RecoveryDecision::bounded_retry(0, 3, FailureKind::StaleNode);
        assert!(matches!(d, RecoveryDecision::ReacquireAndRetry { .. }));
    }

    #[test]
    fn classify_common_errors() {
        assert_eq!(
            classify_error("stale element reference"),
            FailureKind::StaleNode
        );
        assert_eq!(classify_error("Timed out waiting"), FailureKind::Timeout);
        assert_eq!(
            classify_error("something entirely new"),
            FailureKind::Unknown
        );
    }

    #[test]
    fn classify_m1_runtime_errors() {
        // First-class M1 error strings (see browser-core error.rs Display).
        assert_eq!(
            classify_error("tab's target ABC is closed"),
            FailureKind::TargetGone
        );
        assert_eq!(
            classify_error("frame F1 is detached"),
            FailureKind::DetachedFrame
        );
        assert_eq!(
            classify_error("cdp command 'Page.navigate' timed out after 30s"),
            FailureKind::Timeout
        );
        assert_eq!(
            classify_error("cdp error -32601: 'Page.navigate' wasn't found"),
            FailureKind::ProtocolError
        );
        // Terminal connection states escalate with evidence.
        assert_eq!(
            classify_error("connection to the browser was lost"),
            FailureKind::Unknown
        );
        assert_eq!(
            classify_error("browser process exited"),
            FailureKind::Unknown
        );
    }
}
