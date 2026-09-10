//! Action outcome: execution evidence + verification verdict + delta.
//!
//! `CDP command success != task success`: [`ActionOutcome`] always carries
//! both halves, so callers can distinguish "the click was sent" from "the
//! click did the intended thing".

use crate::action::BrowserAction;
use crate::failure::ExecutionFailure;
use browser_agent_observation::SnapshotDelta;
use browser_agent_verification::VerificationResult;
use serde::{Deserialize, Serialize};

/// Evidence that the mechanics ran.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecutionEvidence {
    /// How it was performed (`cdp-input`, `keyboard`, `dom-method`, ...).
    pub method: String,
    pub detail: String,
}

/// `Ok` = mechanics ran; use `verification` for whether it *worked*.
pub type ExecutionResult = Result<ExecutionEvidence, ExecutionFailure>;

/// Mechanical repairs applied across attempts, in order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MechanicalRepair {
    ReResolve,
    ScrollIntoView,
    WaitTransientOverlay,
    RetryHitTest,
    ReacquireAfterMutation,
}

impl MechanicalRepair {
    pub fn as_str(&self) -> &'static str {
        match self {
            MechanicalRepair::ReResolve => "re-resolve",
            MechanicalRepair::ScrollIntoView => "scroll-into-view",
            MechanicalRepair::WaitTransientOverlay => "wait-transient-overlay",
            MechanicalRepair::RetryHitTest => "retry-hit-test",
            MechanicalRepair::ReacquireAfterMutation => "reacquire-after-mutation",
        }
    }
}

/// Complete, self-describing result of one `act()` call.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActionOutcome {
    pub action: BrowserAction,
    pub execution: ExecutionResult,
    pub verification: VerificationResult,
    pub before_generation: u64,
    pub after_generation: u64,
    pub delta: SnapshotDelta,
    #[serde(default)]
    pub repairs: Vec<MechanicalRepair>,
    /// Total perform attempts (bounded by [`crate::policy::MAX_ACTION_ATTEMPTS`]).
    pub attempts: u32,
    pub elapsed_ms: u64,
}

impl ActionOutcome {
    /// True only when the mechanics ran AND the effect was proven.
    pub fn succeeded(&self) -> bool {
        self.execution.is_ok() && self.verification.is_success()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::action::ClickOptions;
    use browser_agent_element_registry::ElementRef;
    use browser_agent_verification::ExpectedEffect;

    #[test]
    fn succeeded_requires_both_halves() {
        let action = BrowserAction::Click {
            target: ElementRef::new(1, "@x", 1),
            options: ClickOptions::default(),
            expected_effect: ExpectedEffect::None,
        };
        let mut outcome = ActionOutcome {
            action,
            execution: Ok(ExecutionEvidence { method: "cdp-input".into(), detail: String::new() }),
            verification: VerificationResult::uncertain("e", "o"),
            before_generation: 1,
            after_generation: 1,
            delta: SnapshotDelta::default(),
            repairs: vec![],
            attempts: 1,
            elapsed_ms: 5,
        };
        assert!(!outcome.succeeded());
        outcome.verification = VerificationResult::success("e", "o");
        assert!(outcome.succeeded());
        let json = serde_json::to_string(&outcome).unwrap();
        let back: ActionOutcome = serde_json::from_str(&json).unwrap();
        assert_eq!(back.attempts, 1);
    }
}
