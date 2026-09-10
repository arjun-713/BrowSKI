//! Validated browser actions.
//!
//! Boundary: defines the [`BrowserAction`] vocabulary and validated
//! [`ActionResult`]. Executes nothing by itself in this slice — execution
//! against a live browser lives in `browser-core` + `cdp`. Contains no agent
//! reasoning and no LLM calls.

use browser_agent_element_registry::ElementRef;
use serde::{Deserialize, Serialize};

/// Validated browser action. `expected_effect` is a human/machine-readable
/// postcondition used by `verification` (e.g. "url becomes ...").
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum BrowserAction {
    Navigate {
        url: String,
        #[serde(default)]
        expected_effect: Option<String>,
    },
    Click {
        target: ElementRef,
        #[serde(default)]
        expected_effect: Option<String>,
    },
    Type {
        target: ElementRef,
        value: String,
        #[serde(default)]
        submit: bool,
        #[serde(default)]
        expected_effect: Option<String>,
    },
    Select {
        target: ElementRef,
        value: String,
        #[serde(default)]
        expected_effect: Option<String>,
    },
    Check {
        target: ElementRef,
        checked: bool,
        #[serde(default)]
        expected_effect: Option<String>,
    },
    Scroll {
        #[serde(default)]
        target: Option<ElementRef>,
        #[serde(default)]
        x: i64,
        #[serde(default)]
        y: i64,
        #[serde(default)]
        expected_effect: Option<String>,
    },
    Press {
        key: String,
        #[serde(default)]
        expected_effect: Option<String>,
    },
    Wait {
        ms: u64,
    },
}

impl BrowserAction {
    /// Every action except raw `Wait` should carry an expected effect so it
    /// can be verified (principle: tool success != action success).
    pub fn requires_expected_effect(&self) -> bool {
        !matches!(self, BrowserAction::Wait { .. })
    }
}

/// Outcome of an executed action (transport-level + before/after state ids).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActionResult {
    pub ok: bool,
    pub action: BrowserAction,
    #[serde(default)]
    pub before_generation: Option<u64>,
    #[serde(default)]
    pub after_generation: Option<u64>,
    #[serde(default)]
    pub evidence: serde_json::Value,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wait_does_not_require_expected_effect() {
        assert!(!BrowserAction::Wait { ms: 100 }.requires_expected_effect());
        assert!(BrowserAction::Navigate {
            url: "https://example.com".into(),
            expected_effect: None
        }
        .requires_expected_effect());
    }

    #[test]
    fn action_serde_tagged() {
        let a = BrowserAction::Click {
            target: ElementRef::new(7, "@x", 1),
            expected_effect: None,
        };
        let v = serde_json::to_value(&a).unwrap();
        assert_eq!(v["type"], "click");
    }
}
