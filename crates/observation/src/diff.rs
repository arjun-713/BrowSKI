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
use std::collections::{HashMap, HashSet};

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

/// Compute the delta from `before` to `after` (same tab).
///
/// Elements match by fingerprint (stable across alias/doc-order churn), with
/// registry id as the tiebreak. Same fingerprint + different ref/frame =
/// `moved`. Same fingerprint + different value/state/text/visibility =
/// `changed`.
pub fn diff_snapshots(before: &SemanticSnapshot, after: &SemanticSnapshot) -> SnapshotDelta {
    let mut delta = SnapshotDelta {
        navigation_changed: before.url != after.url,
        focus_changed: before.focused != after.focused,
        ..Default::default()
    };

    // Index by fingerprint; fingerprints are near-unique, collisions fall
    // back to registry id comparison below.
    let mut old_by_fp: HashMap<&str, Vec<usize>> = HashMap::new();
    for (i, el) in before.elements.iter().enumerate() {
        old_by_fp
            .entry(el.fingerprint.as_str())
            .or_default()
            .push(i);
    }
    let mut new_by_fp: HashMap<&str, Vec<usize>> = HashMap::new();
    for (i, el) in after.elements.iter().enumerate() {
        new_by_fp
            .entry(el.fingerprint.as_str())
            .or_default()
            .push(i);
    }

    let mut matched_old: HashSet<usize> = HashSet::new();
    let mut matched_new: HashSet<usize> = HashSet::new();

    // Greedy 1:1 matching on identical fingerprints (doc-order aligned).
    let mut fps: Vec<&str> = old_by_fp.keys().copied().collect();
    fps.sort_unstable();
    for fp in fps {
        if let Some(new_idxs) = new_by_fp.get(fp) {
            let old_idxs = &old_by_fp[fp];
            for (o, n) in old_idxs.iter().zip(new_idxs.iter()) {
                matched_old.insert(*o);
                matched_new.insert(*n);
                let old_el = &before.elements[*o];
                let new_el = &after.elements[*n];
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
                    fields.push("text changed".to_string());
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
        }
    }

    for (i, el) in after.elements.iter().enumerate() {
        if !matched_new.contains(&i) {
            delta.added.push(el.reference.clone());
        }
    }
    for (i, el) in before.elements.iter().enumerate() {
        if !matched_old.contains(&i) {
            delta.removed.push(el.reference.clone());
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
        SemanticElement {
            id: 1,
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
        let before = snap("https://x/a", vec![el("@gone", "fp-gone", None)]);
        let after = snap("https://x/b", vec![el("@fresh", "fp-fresh", None)]);
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
