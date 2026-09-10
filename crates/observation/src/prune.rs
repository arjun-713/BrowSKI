//! Two representations: full `SemanticSnapshot` internally, pruned
//! `AgentObservation` for the model.
//!
//! Pruning is deterministic (no LLM decides what the LLM sees):
//! interactive elements, form controls, headings, dialogs, alerts, tables,
//! navigation landmarks, important nearby text, recently changed elements,
//! and memory-referenced elements survive. Everything else is dropped with
//! a truncation marker so the model knows the view is partial.

use crate::ids::TabId;
use crate::model::{SemanticElement, SemanticKind, SemanticSnapshot, VisibilityClass};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Hard cap on model-facing elements (truncation marker beyond).
pub const MAX_MODEL_ELEMENTS: usize = 300;

/// One pruned element for model consumption.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PrunedElement {
    #[serde(rename = "ref")]
    pub reference: String,
    pub role: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub state: Vec<String>,
    #[serde(default, skip_serializing_if = "is_true")]
    pub interactable: bool,
}

fn is_true(b: &bool) -> bool {
    *b
}

/// Model-facing observation: pruned, stable, renderable.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AgentObservation {
    pub url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active_tab: Option<TabId>,
    pub state_generation: u64,
    pub page_fingerprint: String,
    pub elements: Vec<PrunedElement>,
    #[serde(default)]
    pub truncated: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub focused: Option<String>,
}

fn keep_kind(kind: SemanticKind) -> bool {
    matches!(
        kind,
        SemanticKind::Button
            | SemanticKind::Link
            | SemanticKind::TextInput
            | SemanticKind::Option
            | SemanticKind::OptionList
            | SemanticKind::Checkable
            | SemanticKind::Heading
            | SemanticKind::Dialog
            | SemanticKind::Alert
            | SemanticKind::Table
            | SemanticKind::Navigation
            | SemanticKind::Form
    )
}

/// Prune a snapshot for the model.
///
/// `changed` are refs from the latest delta (always included);
/// `memory_refs` are refs the agent's working memory cares about.
pub fn prune(
    snapshot: &SemanticSnapshot,
    changed: &HashSet<String>,
    memory_refs: &HashSet<String>,
) -> AgentObservation {
    let mut elements = Vec::new();
    for el in &snapshot.elements {
        let relevant = el.interactable
            || keep_kind(el.semantic_kind)
            || el.visibility == VisibilityClass::Occluded // occlusion is news
            || changed.contains(&el.reference)
            || memory_refs.contains(&el.reference);
        if relevant {
            elements.push(prune_one(el));
        }
    }
    // Stable order: document order is already snapshot order; keep it.
    let truncated = elements.len() > MAX_MODEL_ELEMENTS;
    elements.truncate(MAX_MODEL_ELEMENTS);
    AgentObservation {
        url: snapshot.url.clone(),
        title: snapshot.title.clone(),
        active_tab: snapshot.active_tab.clone(),
        state_generation: snapshot.state_generation,
        page_fingerprint: snapshot.page_fingerprint.clone(),
        elements,
        truncated,
        focused: snapshot.focused.clone(),
    }
}

fn prune_one(el: &SemanticElement) -> PrunedElement {
    PrunedElement {
        reference: el.reference.clone(),
        role: el.role.clone(),
        name: el.accessible_name.clone(),
        text: el.text.clone(),
        value: el.value.clone(),
        state: el.state.clone(),
        interactable: el.interactable,
    }
}

fn fmt_opt(label: &str, value: &Option<String>, out: &mut String) {
    if let Some(v) = value {
        if !v.is_empty() {
            out.push_str(&format!("\n  {label}=\"{v}\""));
        }
    }
}

/// Render the model-facing text form:
///
/// ```text
/// @search_box
///   textbox
///   "Search jobs"
/// ```
pub fn render_text(obs: &AgentObservation) -> String {
    let mut out = String::new();
    for el in &obs.elements {
        out.push_str(&el.reference);
        out.push('\n');
        out.push_str(&format!("  {}", el.role));
        out.push('\n');
        fmt_opt("name", &el.name, &mut out);
        if let Some(t) = &el.text {
            if !t.is_empty() {
                out.push_str(&format!("\n  \"{t}\""));
            }
        }
        fmt_opt("value", &el.value, &mut out);
        if !el.state.is_empty() {
            out.push_str(&format!("\n  [{}]", el.state.join(", ")));
        }
        if !el.interactable {
            out.push_str("\n  (not interactable)");
        }
        out.push('\n');
    }
    if obs.truncated {
        out.push_str("…(truncated: full state has more elements)\n");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{BBox, VisibilityClass};

    fn el(reference: &str, kind: SemanticKind, interactable: bool) -> SemanticElement {
        SemanticElement {
            id: 1,
            reference: reference.into(),
            generation: 1,
            role: "button".into(),
            accessible_name: Some("Go".into()),
            text: None,
            value: None,
            state: vec![],
            bbox: Some(BBox {
                x: 0.0,
                y: 0.0,
                width: 10.0,
                height: 10.0,
            }),
            visible: true,
            visibility: VisibilityClass::Visible,
            enabled: true,
            interactable,
            frame: None,
            frame_path: vec!["main".into()],
            semantic_kind: kind,
            backend_node_id: None,
            doc_order: 0,
            ancestry: vec![],
            confidence: 1.0,
            fingerprint: "fp".into(),
        }
    }

    fn snap(elements: Vec<SemanticElement>) -> SemanticSnapshot {
        let mut s = SemanticSnapshot::minimal("https://x/".into(), None, 1);
        s.elements = elements;
        s
    }

    #[test]
    fn keeps_interactive_drops_generic() {
        let obs = prune(
            &snap(vec![
                el("@go", SemanticKind::Button, true),
                el("@blob", SemanticKind::Generic, false),
            ]),
            &HashSet::new(),
            &HashSet::new(),
        );
        assert_eq!(obs.elements.len(), 1);
        assert_eq!(obs.elements[0].reference, "@go");
        assert!(!obs.truncated);
    }

    #[test]
    fn changed_and_memory_refs_survive() {
        let changed: HashSet<String> = ["@blob".into()].iter().cloned().collect();
        let obs = prune(
            &snap(vec![el("@blob", SemanticKind::Generic, false)]),
            &changed,
            &HashSet::new(),
        );
        assert_eq!(obs.elements.len(), 1);
    }

    #[test]
    fn renders_model_text_form() {
        let obs = prune(
            &snap(vec![el("@go", SemanticKind::Button, true)]),
            &HashSet::new(),
            &HashSet::new(),
        );
        let text = render_text(&obs);
        assert!(text.contains("@go"));
        assert!(text.contains("button"));
    }
}
