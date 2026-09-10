//! Semantic state shapes: elements, snapshots, forms, dialogs, text.
//!
//! The snapshot is NOT a serialized DOM dump. It is a compact, stable,
//! model-friendly projection: named elements with stable refs, prunable to
//! an `AgentObservation` (see `prune`), diffable (`diff`), and fingerprinted
//! from stable signals (never raw HTML).

use crate::ids::{BackendNodeId, FrameId, TabId};
use serde::{Deserialize, Serialize};

fn default_true() -> bool {
    true
}

fn default_confidence() -> f64 {
    1.0
}

fn snapshot_schema_version() -> u32 {
    1
}

/// Deterministic FNV-1a 64-bit hex (no extra deps; stable across runs).
pub fn stable_hash_hex(s: &str) -> String {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in s.bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    format!("{h:x}")
}

/// Bounding box in CSS pixels, relative to the main-frame viewport.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct BBox {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

impl BBox {
    pub fn area(&self) -> f64 {
        self.width.max(0.0) * self.height.max(0.0)
    }

    pub fn is_empty(&self) -> bool {
        self.area() <= 0.0
    }

    pub fn center(&self) -> (f64, f64) {
        (self.x + self.width / 2.0, self.y + self.height / 2.0)
    }
}

/// Viewport dimensions in CSS pixels.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct Viewport {
    #[serde(default)]
    pub width: f64,
    #[serde(default)]
    pub height: f64,
    #[serde(default)]
    pub device_scale_factor: f64,
}

/// Viewport scroll state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ScrollState {
    #[serde(default)]
    pub x: i64,
    #[serde(default)]
    pub y: i64,
}

/// Visibility classification. `display != none` is nowhere near enough:
/// occlusion, viewport intersection, and style all participate (see
/// `filter`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "UPPERCASE")]
pub enum VisibilityClass {
    #[default]
    Visible,
    Hidden,
    Offscreen,
    Occluded,
}

/// Coarse semantic kind used for pruning and model presentation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum SemanticKind {
    #[default]
    Generic,
    Button,
    Link,
    TextInput,
    Option,
    OptionList,
    Checkable,
    Heading,
    Text,
    Region,
    Form,
    Dialog,
    Alert,
    Table,
    Navigation,
    Image,
}

/// A single semantic element: DOM node + AX node + layout + form state,
///
/// so `<div class="x91" onclick>` with an accessible name of "Continue"
/// arrives as `role=button name="Continue" interactable=true` instead of a
/// useless `div`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticElement {
    /// Registry id (opaque internal identity; see `element-registry`).
    #[serde(default)]
    pub id: u64,
    /// Stable semantic reference, e.g. `@search_input`. Serialized as `ref`
    /// (the contract name shared with refs, changes, and pruned views).
    #[serde(rename = "ref")]
    pub reference: String,
    /// State generation in which this ref was (re)bound.
    #[serde(default)]
    pub generation: u64,
    /// ARIA role, e.g. `button`, `textbox`, `link`.
    pub role: String,
    /// Accessible name, if any.
    #[serde(default)]
    pub accessible_name: Option<String>,
    /// Visible text summary.
    #[serde(default)]
    pub text: Option<String>,
    /// Current value summary (for inputs; never raw secrets).
    #[serde(default)]
    pub value: Option<String>,
    /// Element state flags, e.g. `["disabled"]`, `["checked"]`.
    #[serde(default)]
    pub state: Vec<String>,
    /// Bounding box, if known.
    #[serde(default)]
    pub bbox: Option<BBox>,
    /// Whether the element is considered visible (rendered).
    #[serde(default = "default_true")]
    pub visible: bool,
    /// Visibility classification (visible/hidden/offscreen/occluded).
    #[serde(default)]
    pub visibility: VisibilityClass,
    /// Whether the element is enabled (not disabled/inert).
    #[serde(default = "default_true")]
    pub enabled: bool,
    /// Whether the element is actionable *right now* (visible, enabled,
    /// hit-testable, no scroll required).
    #[serde(default = "default_true")]
    pub interactable: bool,
    /// Owning frame.
    #[serde(default)]
    pub frame: Option<FrameId>,
    /// Frame provenance path, e.g. `["main", "iframe[checkout]"]`.
    #[serde(default)]
    pub frame_path: Vec<String>,
    /// Coarse semantic kind.
    #[serde(default)]
    pub semantic_kind: SemanticKind,
    /// CDP backend node id (level-1 reacquisition signal).
    #[serde(default)]
    pub backend_node_id: Option<BackendNodeId>,
    /// Document order index (stable within one document snapshot).
    #[serde(default)]
    pub doc_order: u64,
    /// Ancestor tag signatures (`>>shadow` marks shadow boundaries).
    #[serde(default)]
    pub ancestry: Vec<String>,
    /// Collection confidence 0.0..=1.0.
    #[serde(default = "default_confidence")]
    pub confidence: f64,
    /// Stable multi-signal fingerprint for reacquisition.
    pub fingerprint: String,
}

/// A non-interactive text unit (headings, important nearby text).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TextBlock {
    pub kind: TextKind,
    #[serde(default)]
    pub level: Option<u32>,
    pub text: String,
    #[serde(default)]
    pub frame_path: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextKind {
    Heading,
    Paragraph,
    Alert,
}

/// A form and the refs of its controls.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FormSummary {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub controls: Vec<String>,
    #[serde(default)]
    pub submit: Option<String>,
    #[serde(default)]
    pub frame_path: Vec<String>,
}

/// An open dialog/alertdialog.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DialogSummary {
    pub kind: String,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub modal: bool,
    #[serde(default)]
    pub frame_path: Vec<String>,
}

/// Point-in-time browser-visible state for one page/tab.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticSnapshot {
    /// Schema version for serialized snapshots.
    #[serde(default = "snapshot_schema_version")]
    pub schema_version: u32,
    pub url: String,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub tabs: Vec<TabId>,
    #[serde(default)]
    pub active_tab: Option<TabId>,
    #[serde(default)]
    pub active_frame: Option<FrameId>,
    #[serde(default)]
    pub viewport: Viewport,
    #[serde(default)]
    pub scroll: ScrollState,
    /// Interactive elements observed (bounded; see working-memory rules).
    /// M2 also fills `elements`; this stays populated for compatibility.
    #[serde(default)]
    pub interactive_elements: Vec<SemanticElement>,
    /// Full semantic node list (interactive + headings + regions + alerts).
    #[serde(default)]
    pub elements: Vec<SemanticElement>,
    /// Relevant visible text excerpt (bounded).
    #[serde(default)]
    pub text_excerpt: Option<String>,
    /// Non-interactive text blocks (headings, alerts).
    #[serde(default)]
    pub text_blocks: Vec<TextBlock>,
    /// Number of forms detected.
    #[serde(default)]
    pub form_count: usize,
    /// Form details.
    #[serde(default)]
    pub forms: Vec<FormSummary>,
    /// Open dialogs, if any (names).
    #[serde(default)]
    pub dialogs: Vec<String>,
    /// Dialog details.
    #[serde(default)]
    pub dialog_summaries: Vec<DialogSummary>,
    /// Currently focused element ref, if known.
    #[serde(default)]
    pub focused: Option<String>,
    /// Hash of stable page signals for diffing/stagnation (never raw HTML).
    pub page_fingerprint: String,
    /// Monotonic state generation counter for this session.
    pub state_generation: u64,
}

impl SemanticSnapshot {
    /// Minimal snapshot (URL + title only). Keeps the M0/M1 surface working.
    pub fn minimal(url: String, title: Option<String>, state_generation: u64) -> Self {
        let page_fingerprint =
            stable_hash_hex(&format!("{url}|{}", title.as_deref().unwrap_or("")));
        Self {
            schema_version: 1,
            url,
            title,
            tabs: Vec::new(),
            active_tab: None,
            active_frame: None,
            viewport: Viewport::default(),
            scroll: ScrollState::default(),
            interactive_elements: Vec::new(),
            elements: Vec::new(),
            text_excerpt: None,
            text_blocks: Vec::new(),
            form_count: 0,
            forms: Vec::new(),
            dialogs: Vec::new(),
            dialog_summaries: Vec::new(),
            focused: None,
            page_fingerprint,
            state_generation,
        }
    }

    /// Look up an element by model-facing ref.
    pub fn by_ref(&self, reference: &str) -> Option<&SemanticElement> {
        self.elements.iter().find(|e| e.reference == reference)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn minimal_snapshot_round_trips() {
        let s = SemanticSnapshot::minimal("https://example.com".into(), Some("Example".into()), 1);
        let json = serde_json::to_string(&s).unwrap();
        let back: SemanticSnapshot = serde_json::from_str(&json).unwrap();
        assert_eq!(s, back);
        assert_eq!(back.title.as_deref(), Some("Example"));
    }

    #[test]
    fn extended_snapshot_is_backward_compatible() {
        // Old payloads (M0/M1 shape) must still parse.
        let old = serde_json::json!({
            "url": "https://example.com",
            "title": "Example",
            "interactive_elements": [],
            "page_fingerprint": "abc",
            "state_generation": 3
        });
        let s: SemanticSnapshot = serde_json::from_value(old).unwrap();
        assert!(s.elements.is_empty());
        assert!(s.forms.is_empty());
        assert_eq!(s.active_tab, None);
    }

    #[test]
    fn bbox_helpers() {
        let b = BBox {
            x: 0.0,
            y: 0.0,
            width: 10.0,
            height: 5.0,
        };
        assert_eq!(b.area(), 50.0);
        assert_eq!(b.center(), (5.0, 2.5));
        assert!(BBox::default().is_empty());
    }
}
