//! Execution-level failure taxonomy. Every failure carries a kind,
//! evidence, and a retryability judgment — never just a string.
//!
//! Mapping note: `NoEffect`/`WrongEffect` surface through *verification*
//! (`Failure` with check `no-effect`); they are listed here so reporters
//! share one vocabulary.

use serde::{Deserialize, Serialize};

/// Structured failure kinds owned by the executor.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ExecutionFailureKind {
    StaleTarget,
    AmbiguousTarget,
    TargetNotFound,
    TargetHidden,
    TargetOccluded,
    TargetDisabled,
    TargetReadonly,
    FrameDetached,
    TabClosed,
    NavigationRace,
    ActionTimeout,
    InteractionRejected,
    NoEffect,
    WrongEffect,
    DialogBlocked,
    ConnectionLost,
}

impl ExecutionFailureKind {
    /// Whether the same intended action may be retried mechanically.
    /// Strategy changes are never mechanical (M4+ recovery owns those).
    pub fn retryable(self) -> bool {
        match self {
            ExecutionFailureKind::StaleTarget
            | ExecutionFailureKind::TargetNotFound
            | ExecutionFailureKind::TargetOccluded
            | ExecutionFailureKind::NavigationRace
            | ExecutionFailureKind::ActionTimeout
            | ExecutionFailureKind::InteractionRejected => true,
            ExecutionFailureKind::AmbiguousTarget
            | ExecutionFailureKind::TargetHidden
            | ExecutionFailureKind::TargetDisabled
            | ExecutionFailureKind::TargetReadonly
            | ExecutionFailureKind::FrameDetached
            | ExecutionFailureKind::TabClosed
            | ExecutionFailureKind::NoEffect
            | ExecutionFailureKind::WrongEffect
            | ExecutionFailureKind::DialogBlocked
            | ExecutionFailureKind::ConnectionLost => false,
        }
    }
}

/// One failed execution with evidence.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecutionFailure {
    pub kind: ExecutionFailureKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<String>,
    pub details: String,
    pub retryable: bool,
    #[serde(default)]
    pub evidence: serde_json::Value,
}

impl ExecutionFailure {
    pub fn new(
        kind: ExecutionFailureKind,
        target: Option<String>,
        details: impl Into<String>,
    ) -> Self {
        Self {
            kind,
            target,
            details: details.into(),
            retryable: kind.retryable(),
            evidence: serde_json::Value::Null,
        }
    }

    pub fn with_evidence(mut self, evidence: serde_json::Value) -> Self {
        self.evidence = evidence;
        self
    }
}

impl std::fmt::Display for ExecutionFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}: {}", self.kind, self.details)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retryability_is_conservative() {
        assert!(ExecutionFailureKind::StaleTarget.retryable());
        assert!(!ExecutionFailureKind::AmbiguousTarget.retryable());
        assert!(ExecutionFailureKind::TargetOccluded.retryable());
        assert!(!ExecutionFailureKind::ConnectionLost.retryable());
        let f = ExecutionFailure::new(
            ExecutionFailureKind::TargetDisabled,
            Some("@x".into()),
            "disabled",
        );
        assert!(!f.retryable);
        assert_eq!(f.target.as_deref(), Some("@x"));
    }
}
