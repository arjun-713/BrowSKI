//! Incremental state: diff two snapshots into a `SnapshotDelta`.
//!
//! For a form action, the agent should see:
//!
//! ```text
//! Changed:
//! ~ @state value: "" → "Karnataka"
//! + @city option list
//! ```
//!
//! instead of the whole page again. Matching is by stable fingerprint first,
//! registry id second; everything here is deterministic.

use crate::model::SemanticSnapshot;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// One changed element: ref + human-readable field deltas.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ElementChange {
    #[serde(rename = "ref")]
    pub reference: String,
    pub fields: Vec<String>,
}

/// Incremental difference between two snapshots of the same tab.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct SnapshotDelta {
    #[serde(default)]
    pub added: Vec<String>,
    #[serde(default)]
    pub removed: Vec<String>,
    #[serde(default)]
    pub changed: Vec<ElementChange>,
    #[serde(default)]
    pub moved: Vec<String>,
    #[serde(default)]
    pub navigation_changed: bool,
    #[serde(default)]
    pub focus_changed: bool,
}

impl SnapshotDelta {
    pub fn is_empty(&self) -> bool {
        self.added.is_empty()
            && self.removed.is_empty()
            && self.changed.is_empty()
            && self.moved.is_empty()
            && !self.navigation_changed
            && !self.focus_changed
    }
}

fn summarize_opt(v: &Option<String>) -> &str {
    v.as_deref().unwrap_or("")
}

fn truncate80(s: &str) -> String {
    s.chars().take(80).collect()
}

/// Compute the delta from `before` to `after` (same tab).
///
/// Elements match by **registry id** (stable identity); fingerprints back
/// the reacquisition layer, not the diff. Same id + different ref/frame =
/// `moved`. Same id + different value/state/text/visibility = `changed`.
/// Deterministic: outputs sort by reference.
pub fn diff_snapshots(before: &SemanticSnapshot, after: &SemanticSnapshot) -> SnapshotDelta {
    let mut delta = SnapshotDelta {
        navigation_changed: before.url != after.url,
        focus_changed: before.focused != after.focused,
        ..Default::default()
    };

    // Match by registry id (stable identity); fingerprints back the
    // reacquisition layer, not the diff.
    let mut old_by_id: HashMap<u64, usize> = HashMap::new();
    for (i, el) in before.elements.iter().enumerate() {
        old_by_id.insert(el.id, i);
    }
    let mut new_by_id: HashMap<u64, usize> = HashMap::new();
    for (i, el) in after.elements.iter().enumerate() {
        new_by_id.insert(el.id, i);
    }

    // Deterministic union order: before-order, then new-only in after-order.
    let mut order: Vec<u64> = before.elements.iter().map(|e| e.id).collect();
    for el in &after.elements {
        if !old_by_id.contains_key(&el.id) {
            order.push(el.id);
        }
    }

    for id in order {
        match (old_by_id.get(&id), new_by_id.get(&id)) {
            (Some(&o), Some(&n)) => {
                let old_el = &before.elements[o];
                let new_el = &after.elements[n];
                let mut fields = Vec::new();
                if summarize_opt(&old_el.value) != summarize_opt(&new_el.value) {
                    fields.push(format!(
                        "value: {:?} → {:?}",
                        summarize_opt(&old_el.value),
                        summarize_opt(&new_el.value)
                    ));
                }
                if old_el.state != new_el.state {
                    fields.push(format!("state: {:?} → {:?}", old_el.state, new_el.state));
                }
                if summarize_opt(&old_el.text) != summarize_opt(&new_el.text) {
                    fields.push(format!(
                        "text: {:?} → {:?}",
                        truncate80(summarize_opt(&old_el.text)),
                        truncate80(summarize_opt(&new_el.text))
                    ));
                }
                if old_el.visibility != new_el.visibility
                    || old_el.interactable != new_el.interactable
                {
                    fields.push(format!(
                        "visibility: {:?} → {:?}",
                        old_el.visibility, new_el.visibility
                    ));
                }
                if !fields.is_empty() {
                    delta.changed.push(ElementChange {
                        reference: new_el.reference.clone(),
                        fields,
                    });
                }
                if old_el.reference != new_el.reference || old_el.frame_path != new_el.frame_path {
                    delta.moved.push(new_el.reference.clone());
                }
            }
            (None, Some(&n)) => delta.added.push(after.elements[n].reference.clone()),
            (Some(&o), None) => delta.removed.push(before.elements[o].reference.clone()),
            (None, None) => unreachable!("union member missing from both sides"),
        }
    }

    delta.added.sort();
    delta.removed.sort();
    delta.moved.sort();
    delta.changed.sort_by(|a, b| a.reference.cmp(&b.reference));
    delta
}

/// Stable page fingerprint from stable signals (never raw HTML): normalized
/// URL, headings, semantic element structure, form structure, important text.
pub fn page_fingerprint(
    url: &str,
    headings: &[String],
    structure: &[(String, String)],
    forms: &[String],
    text_hash: &str,
) -> String {
    let mut parts = vec![url.to_string()];
    let mut heads = headings.to_vec();
    heads.sort();
    parts.push(heads.join("|"));
    let mut structural: Vec<String> = structure.iter().map(|(r, n)| format!("{r}:{n}")).collect();
    structural.sort();
    parts.push(structural.join("|"));
    let mut form_list = forms.to_vec();
    form_list.sort();
    parts.push(form_list.join("|"));
    parts.push(text_hash.to_string());
    crate::model::stable_hash_hex(&parts.join("||"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{BBox, SemanticElement, SemanticKind, VisibilityClass};

    fn el(reference: &str, fp: &str, value: Option<&str>) -> SemanticElement {
        el_id(reference, fp, value, 1)
    }

    fn el_id(reference: &str, fp: &str, value: Option<&str>, id: u64) -> SemanticElement {
        SemanticElement {
            id,
            reference: reference.into(),
            generation: 1,
            role: "textbox".into(),
            accessible_name: Some(reference.into()),
            text: None,
            value: value.map(str::to_string),
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
            interactable: true,
            frame: None,
            frame_path: vec!["main".into()],
            semantic_kind: SemanticKind::TextInput,
            backend_node_id: None,
            doc_order: 0,
            ancestry: vec![],
            confidence: 1.0,
            fingerprint: fp.into(),
        }
    }

    fn snap(url: &str, elements: Vec<SemanticElement>) -> SemanticSnapshot {
        let mut s = SemanticSnapshot::minimal(url.into(), None, 1);
        s.elements = elements;
        s.interactive_elements = s.elements.clone();
        s
    }

    #[test]
    fn detects_value_change() {
        let before = snap("https://x/", vec![el("@state", "fp1", Some(""))]);
        let after = snap("https://x/", vec![el("@state", "fp1", Some("Karnataka"))]);
        let d = diff_snapshots(&before, &after);
        assert_eq!(d.added.len(), 0);
        assert_eq!(d.removed.len(), 0);
        assert_eq!(d.changed.len(), 1);
        assert!(d.changed[0].fields.iter().any(|f| f.contains("Karnataka")));
        assert!(!d.navigation_changed);
    }

    #[test]
    fn detects_added_removed_and_navigation() {
        let before = snap("https://x/a", vec![el_id("@gone", "fp-gone", None, 1)]);
        let after = snap("https://x/b", vec![el_id("@fresh", "fp-fresh", None, 2)]);
        let d = diff_snapshots(&before, &after);
        assert_eq!(d.added, vec!["@fresh"]);
        assert_eq!(d.removed, vec!["@gone"]);
        assert!(d.navigation_changed);
    }

    #[test]
    fn detects_moved_alias() {
        let mut moved = el("@state", "fp1", None);
        moved.reference = "@state_2".into();
        let before = snap("https://x/", vec![el("@state", "fp1", None)]);
        let after = snap("https://x/", vec![moved]);
        let d = diff_snapshots(&before, &after);
        assert_eq!(d.moved, vec!["@state_2"]);
        assert!(d.added.is_empty() && d.removed.is_empty());
    }

    #[test]
    fn empty_delta_for_identical() {
        let s = snap("https://x/", vec![el("@a", "fp-a", None)]);
        assert!(diff_snapshots(&s, &s).is_empty());
    }

    #[test]
    fn page_fingerprint_ignores_order() {
        let a = page_fingerprint(
            "https://x/",
            &["B".into(), "A".into()],
            &[("button".into(), "go".into())],
            &[],
            "t",
        );
        let b = page_fingerprint(
            "https://x/",
            &["A".into(), "B".into()],
            &[("button".into(), "go".into())],
            &[],
            "t",
        );
        assert_eq!(a, b);
    }
}
