//! Action verification: postconditions, before/after comparison, evidence.
//!
//! Boundary: pure evaluation of `expected vs observed`. Principle: a tool
//! call completing without exception does NOT mean the intended action
//! succeeded — every browser action must be verified.

use browser_agent_executor::BrowserAction;
use browser_agent_observation::SemanticSnapshot;
use serde::{Deserialize, Serialize};

/// Verification outcome.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum VerificationStatus {
    Success,
    Failure,
    Uncertain,
}

/// Structured verification result with evidence.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VerificationResult {
    pub status: VerificationStatus,
    pub expected: String,
    pub observed: String,
    #[serde(default)]
    pub evidence: serde_json::Value,
    #[serde(default)]
    pub state_delta: serde_json::Value,
}

impl VerificationResult {
    pub fn success(expected: impl Into<String>, observed: impl Into<String>) -> Self {
        Self {
            status: VerificationStatus::Success,
            expected: expected.into(),
            observed: observed.into(),
            evidence: serde_json::Value::Null,
            state_delta: serde_json::Value::Null,
        }
    }

    pub fn failure(expected: impl Into<String>, observed: impl Into<String>) -> Self {
        Self {
            status: VerificationStatus::Failure,
            expected: expected.into(),
            observed: observed.into(),
            evidence: serde_json::Value::Null,
            state_delta: serde_json::Value::Null,
        }
    }

    pub fn uncertain(expected: impl Into<String>, observed: impl Into<String>) -> Self {
        Self {
            status: VerificationStatus::Uncertain,
            expected: expected.into(),
            observed: observed.into(),
            evidence: serde_json::Value::Null,
            state_delta: serde_json::Value::Null,
        }
    }

    pub fn is_success(&self) -> bool {
        self.status == VerificationStatus::Success
    }
}

/// Verify a navigation: expected URL (substring match) vs observed snapshot.
pub fn verify_navigation(
    action: &BrowserAction,
    before: &SemanticSnapshot,
    after: &SemanticSnapshot,
) -> VerificationResult {
    let expected_url = match action {
        BrowserAction::Navigate { url, .. } => url.clone(),
        _ => {
            return VerificationResult::uncertain(
                "navigation",
                format!("action is not a navigation: {action:?}"),
            )
        }
    };
    let normalize = |u: &str| u.trim_end_matches('/').to_lowercase();
    let result = if normalize(&after.url).contains(&normalize(&expected_url))
        || normalize(&expected_url).contains(&normalize(&after.url))
    {
        VerificationResult::success(
            format!("url becomes {expected_url}"),
            format!("url is {}", after.url),
        )
    } else {
        VerificationResult::failure(
            format!("url becomes {expected_url}"),
            format!("url is {}", after.url),
        )
    };
    VerificationResult {
        evidence: serde_json::json!({
            "before_url": before.url,
            "after_url": after.url,
            "before_generation": before.state_generation,
            "after_generation": after.state_generation,
        }),
        state_delta: serde_json::json!({
            "url_changed": before.url != after.url,
            "title_changed": before.title != after.title,
        }),
        ..result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snap(url: &str) -> SemanticSnapshot {
        SemanticSnapshot::minimal(url.into(), None, 1)
    }

    #[test]
    fn navigation_success_when_urls_match() {
        let action = BrowserAction::Navigate {
            url: "https://example.com".into(),
            expected_effect: None,
        };
        let r = verify_navigation(&action, &snap("about:blank"), &snap("https://example.com/"));
        assert!(r.is_success());
    }

    #[test]
    fn navigation_failure_when_urls_differ() {
        let action = BrowserAction::Navigate {
            url: "https://example.com".into(),
            expected_effect: None,
        };
        let r = verify_navigation(&action, &snap("about:blank"), &snap("https://other.test/"));
        assert_eq!(r.status, VerificationStatus::Failure);
    }
}
