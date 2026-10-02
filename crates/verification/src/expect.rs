//! Action expectations and tri-state verification.
//!
//! A `BrowserAction` carries an [`ExpectedEffect`]; after performing it, the
//! runtime checks each [`EffectExpectation`] against before/after snapshots,
//! the [`SnapshotDelta`], and observed [`SideEffects`]. Outcomes are
//! tri-state: `Success` (proven), `Failure` (disproven), `Uncertain`
//! (insufficient evidence — never call this success).

use browser_agent_element_registry::ElementRef;
use browser_agent_observation::{SemanticSnapshot, SnapshotDelta};
use serde::{Deserialize, Serialize};

/// One checkable postcondition on a browser state transition.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "expect", rename_all = "snake_case")]
pub enum EffectExpectation {
    UrlChanged,
    UrlIs {
        url: String,
    },
    ElementAppeared {
        reference: String,
    },
    ElementDisappeared {
        reference: String,
    },
    ValueIs {
        target: ElementRef,
        value: String,
    },
    CheckedIs {
        target: ElementRef,
        checked: bool,
    },
    StateContains {
        target: ElementRef,
        state: String,
    },
    DialogOpened,
    DialogClosed,
    NewTabOpened,
    /// Any observable state change (delta non-empty). Weak on its own —
    /// prefer specific expectations where the test knows them.
    AnyElementChanged,
}

/// Declared postcondition of an action.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ExpectedEffect {
    /// No declaration: per-action defaults apply (see [`default_effect_for`]).
    #[default]
    Unspecified,
    /// Explicitly nothing to prove (rare; most actions verify directly).
    None,
    /// At least one expectation must be met.
    AnyOf(Vec<EffectExpectation>),
}

/// Per-action default expectations, keyed by action-type name so this crate
/// never imports the action enum (layering: executor → verification).
pub fn default_effect_for(action_type: &str) -> ExpectedEffect {
    match action_type {
        // A click must observably do *something*.
        "click" => ExpectedEffect::AnyOf(vec![
            EffectExpectation::UrlChanged,
            EffectExpectation::DialogOpened,
            EffectExpectation::NewTabOpened,
            EffectExpectation::AnyElementChanged,
        ]),
        "press" | "hover" => ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
        "new_tab" => ExpectedEffect::AnyOf(vec![EffectExpectation::NewTabOpened]),
        "handle_dialog" => ExpectedEffect::AnyOf(vec![EffectExpectation::DialogClosed]),
        // Type/select/check/scroll/navigate verify directly from read-back
        // and carry their own checks; Unspecified lets the caller decide.
        _ => ExpectedEffect::Unspecified,
    }
}

/// Side effects observed during the verification window (filled by the
/// runtime from its event drain; pure data here).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct SideEffects {
    #[serde(default)]
    pub url_changed: bool,
    #[serde(default)]
    pub dialog_opened: bool,
    #[serde(default)]
    pub dialog_closed: bool,
    #[serde(default)]
    pub new_tab_opened: bool,
    #[serde(default)]
    pub tab_closed: bool,
}

/// Verdict for a single expectation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExpectationVerdict {
    Met(String),
    Unmet(String),
    Uncertain(String),
}

/// Check one expectation against before/after state.
pub fn check_expectation(
    exp: &EffectExpectation,
    before: &SemanticSnapshot,
    after: &SemanticSnapshot,
    delta: &SnapshotDelta,
    side: &SideEffects,
) -> ExpectationVerdict {
    match exp {
        EffectExpectation::UrlChanged => {
            if before.url != after.url || side.url_changed || delta.navigation_changed {
                ExpectationVerdict::Met(format!("url {} → {}", before.url, after.url))
            } else {
                ExpectationVerdict::Unmet("url unchanged".into())
            }
        }
        EffectExpectation::UrlIs { url } => {
            if normalize_url(&after.url) == normalize_url(url) {
                ExpectationVerdict::Met(format!("url is {}", after.url))
            } else {
                ExpectationVerdict::Unmet(format!("url is {}, expected {url}", after.url))
            }
        }
        EffectExpectation::ElementAppeared { reference } => {
            if after.by_ref(reference).is_some() {
                ExpectationVerdict::Met(format!("{reference} present"))
            } else {
                ExpectationVerdict::Unmet(format!("{reference} absent"))
            }
        }
        EffectExpectation::ElementDisappeared { reference } => {
            if after.by_ref(reference).is_none() {
                ExpectationVerdict::Met(format!("{reference} gone"))
            } else {
                ExpectationVerdict::Unmet(format!("{reference} still present"))
            }
        }
        EffectExpectation::ValueIs { target, value } => {
            match after.elements.iter().find(|e| e.id == target.id) {
                Some(el) if el.value.as_deref().unwrap_or("") == value => {
                    ExpectationVerdict::Met(format!("{} == {value:?}", target))
                }
                Some(el) => ExpectationVerdict::Unmet(format!(
                    "{} == {:?}, expected {value:?}",
                    target,
                    el.value.as_deref().unwrap_or("")
                )),
                None => ExpectationVerdict::Uncertain(format!("{target} not in snapshot")),
            }
        }
        EffectExpectation::CheckedIs { target, checked } => {
            match after.elements.iter().find(|e| e.id == target.id) {
                Some(el) => {
                    let is_checked = el.state.iter().any(|s| s == "checked");
                    if is_checked == *checked {
                        ExpectationVerdict::Met(format!("{target} checked={checked}"))
                    } else {
                        ExpectationVerdict::Unmet(format!(
                            "{target} checked={is_checked}, expected {checked}"
                        ))
                    }
                }
                None => ExpectationVerdict::Uncertain(format!("{target} not in snapshot")),
            }
        }
        EffectExpectation::StateContains { target, state } => {
            match after.elements.iter().find(|e| e.id == target.id) {
                Some(el) if el.state.iter().any(|s| s == state) => {
                    ExpectationVerdict::Met(format!("{target} has state {state}"))
                }
                Some(_) => ExpectationVerdict::Unmet(format!("{target} lacks state {state}")),
                None => ExpectationVerdict::Uncertain(format!("{target} not in snapshot")),
            }
        }
        EffectExpectation::DialogOpened => {
            if side.dialog_opened || !after.dialog_summaries.is_empty() {
                ExpectationVerdict::Met("dialog open".into())
            } else {
                ExpectationVerdict::Unmet("no dialog observed".into())
            }
        }
        EffectExpectation::DialogClosed => {
            if side.dialog_closed {
                ExpectationVerdict::Met("dialog closed".into())
            } else {
                ExpectationVerdict::Unmet("dialog did not close".into())
            }
        }
        EffectExpectation::NewTabOpened => {
            if side.new_tab_opened {
                ExpectationVerdict::Met("new tab observed".into())
            } else {
                ExpectationVerdict::Unmet("no new tab observed".into())
            }
        }
        EffectExpectation::AnyElementChanged => {
            // Focus-only movement is mechanical, not task progress: a click
            // that merely focuses its target is NO_EFFECT, not success.
            let substantive = !delta.added.is_empty()
                || !delta.removed.is_empty()
                || !delta.moved.is_empty()
                || delta.changed.iter().any(|c| {
                    let old_el = before.elements.iter().find(|e| e.reference == c.reference);
                    let new_el = after.elements.iter().find(|e| e.reference == c.reference);
                    match (old_el, new_el) {
                        (Some(o), Some(n)) => substantive_change(o, n),
                        _ => true,
                    }
                });
            if substantive {
                ExpectationVerdict::Met(format!(
                    "state changed (+{}/-{}/~{})",
                    delta.added.len(),
                    delta.removed.len(),
                    delta.changed.len()
                ))
            } else {
                ExpectationVerdict::Unmet(
                    "no substantive state change (focus moved at most)".into(),
                )
            }
        }
    }
}

fn normalize_url(u: &str) -> String {
    u.trim_end_matches('/').to_lowercase()
}

/// True if anything changed apart from focus movement.
fn substantive_change(
    old_el: &browser_agent_observation::SemanticElement,
    new_el: &browser_agent_observation::SemanticElement,
) -> bool {
    if browser_agent_observation::opt_str(&old_el.value)
        != browser_agent_observation::opt_str(&new_el.value)
    {
        return true;
    }
    if browser_agent_observation::opt_str(&old_el.text)
        != browser_agent_observation::opt_str(&new_el.text)
    {
        return true;
    }
    if old_el.visibility != new_el.visibility || old_el.interactable != new_el.interactable {
        return true;
    }
    let without_focus = |states: &[String]| {
        states
            .iter()
            .filter(|s| s.as_str() != "focused")
            .cloned()
            .collect::<Vec<_>>()
    };
    without_focus(&old_el.state) != without_focus(&new_el.state)
}

/// Verify a declared effect: Success if any expectation is met, Failure if
/// all are unmet, Uncertain if none met but at least one is uncertain.
///
/// `check` names the deciding expectation for evidence/telemetry.
pub fn verify_expected(
    expected: &ExpectedEffect,
    action_type: &str,
    before: &SemanticSnapshot,
    after: &SemanticSnapshot,
    delta: &SnapshotDelta,
    side: &SideEffects,
) -> crate::VerificationResult {
    let effective = match expected {
        ExpectedEffect::Unspecified => default_effect_for(action_type),
        other => other.clone(),
    };
    match effective {
        ExpectedEffect::None => {
            crate::VerificationResult::success("no postcondition", "declared none")
                .with_check("none")
        }
        ExpectedEffect::Unspecified => crate::VerificationResult::uncertain(
            "no expectations",
            "no declared or default expectations apply",
        )
        .with_check("unspecified"),
        ExpectedEffect::AnyOf(list) if list.is_empty() => {
            crate::VerificationResult::uncertain("empty expectations", "no expectations to check")
                .with_check("empty")
        }
        ExpectedEffect::AnyOf(list) => {
            let mut unmets = Vec::new();
            let mut uncertains = Vec::new();
            for exp in &list {
                match check_expectation(exp, before, after, delta, side) {
                    ExpectationVerdict::Met(msg) => {
                        return crate::VerificationResult::success(
                            format!("{action_type} had an effect"),
                            msg,
                        )
                        .with_check(expectation_name(exp));
                    }
                    ExpectationVerdict::Unmet(msg) => {
                        unmets.push(format!("{}: {msg}", expectation_name(exp)))
                    }
                    ExpectationVerdict::Uncertain(msg) => {
                        uncertains.push(format!("{}: {msg}", expectation_name(exp)))
                    }
                }
            }
            if unmets.len() == list.len() {
                crate::VerificationResult::failure(
                    format!("{action_type} had an effect"),
                    unmets.join("; "),
                )
                .with_check("no-effect")
            } else {
                crate::VerificationResult::uncertain(
                    format!("{action_type} had an effect"),
                    uncertains.join("; "),
                )
                .with_check("uncertain-effect")
            }
        }
    }
}

fn expectation_name(exp: &EffectExpectation) -> &'static str {
    match exp {
        EffectExpectation::UrlChanged => "url-changed",
        EffectExpectation::UrlIs { .. } => "url-is",
        EffectExpectation::ElementAppeared { .. } => "element-appeared",
        EffectExpectation::ElementDisappeared { .. } => "element-disappeared",
        EffectExpectation::ValueIs { .. } => "value-is",
        EffectExpectation::CheckedIs { .. } => "checked-is",
        EffectExpectation::StateContains { .. } => "state-contains",
        EffectExpectation::DialogOpened => "dialog-opened",
        EffectExpectation::DialogClosed => "dialog-closed",
        EffectExpectation::NewTabOpened => "new-tab-opened",
        EffectExpectation::AnyElementChanged => "any-element-changed",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use browser_agent_observation::{SemanticElement, SemanticKind, VisibilityClass};

    fn el(reference: &str, id: u64, value: Option<&str>) -> SemanticElement {
        SemanticElement {
            id,
            reference: reference.into(),
            generation: 1,
            role: "textbox".into(),
            accessible_name: Some(reference.into()),
            text: None,
            value: value.map(str::to_string),
            state: vec![],
            bbox: None,
            visible: true,
            visibility: VisibilityClass::Visible,
            enabled: true,
            interactable: true,
            frame: None,
            frame_path: vec!["main".into()],
            semantic_kind: SemanticKind::TextInput,
            backend_node_id: None,
            doc_order: 0,
            ancestry: vec![],
            confidence: 1.0,
            fingerprint: format!("fp-{reference}"),
        }
    }

    fn snap(url: &str, elements: Vec<SemanticElement>) -> SemanticSnapshot {
        let mut s = SemanticSnapshot::minimal(url.into(), None, 1);
        s.elements = elements;
        s
    }

    fn target(id: u64, alias: &str) -> ElementRef {
        ElementRef::new(id, alias, 1)
    }

    #[test]
    fn value_is_proven_or_disproven() {
        let before = snap("https://x/", vec![el("@u", 1, Some(""))]);
        let after = snap("https://x/", vec![el("@u", 1, Some("mallik"))]);
        let delta = browser_agent_observation::diff_snapshots(&before, &after);
        let side = SideEffects::default();
        let met = check_expectation(
            &EffectExpectation::ValueIs {
                target: target(1, "@u"),
                value: "mallik".into(),
            },
            &before,
            &after,
            &delta,
            &side,
        );
        assert!(matches!(met, ExpectationVerdict::Met(_)));
        let unmet = check_expectation(
            &EffectExpectation::ValueIs {
                target: target(1, "@u"),
                value: "other".into(),
            },
            &before,
            &after,
            &delta,
            &side,
        );
        assert!(matches!(unmet, ExpectationVerdict::Unmet(_)));
    }

    #[test]
    fn missing_target_is_uncertain_not_failure() {
        let s = snap("https://x/", vec![]);
        let v = check_expectation(
            &EffectExpectation::ValueIs {
                target: target(9, "@gone"),
                value: "x".into(),
            },
            &s,
            &s,
            &SnapshotDelta::default(),
            &SideEffects::default(),
        );
        assert!(matches!(v, ExpectationVerdict::Uncertain(_)));
    }

    #[test]
    fn any_of_prefers_success_over_uncertainty_over_failure() {
        let s = snap("https://x/", vec![]);
        let r = verify_expected(
            &ExpectedEffect::AnyOf(vec![
                EffectExpectation::UrlChanged,
                EffectExpectation::ValueIs {
                    target: target(9, "@gone"),
                    value: "x".into(),
                },
            ]),
            "click",
            &s,
            &s,
            &SnapshotDelta::default(),
            &SideEffects::default(),
        );
        // UrlChanged is Unmet, ValueIs is Uncertain → overall Uncertain.
        assert_eq!(r.status, crate::VerificationStatus::Uncertain);
        let r2 = verify_expected(
            &ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged]),
            "click",
            &s,
            &s,
            &SnapshotDelta::default(),
            &SideEffects::default(),
        );
        assert_eq!(r2.status, crate::VerificationStatus::Failure);
        assert_eq!(r2.check, "no-effect");
    }

    #[test]
    fn url_change_proves_click() {
        let before = snap("https://x/a", vec![]);
        let after = snap("https://x/b", vec![]);
        let r = verify_expected(
            &ExpectedEffect::Unspecified,
            "click",
            &before,
            &after,
            &SnapshotDelta::default(),
            &SideEffects::default(),
        );
        assert!(r.is_success());
    }
}
