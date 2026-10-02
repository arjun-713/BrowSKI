//! Browser-visible state: DOM, accessibility, layout, visibility, forms,
//! page metadata, and the [`SemanticSnapshot`] type.
//!
//! Boundary: pure data + shaping (fingerprinting, aliases, classification,
//! pruning, diffing). No CDP transport here (see the `cdp` crate), no action
//! execution (see `executor`), no LLM calls.
//!
//! Philosophy (see `docs/architecture/observation-model.md`): browser-native
//! semantics (DOM + accessibility + layout) come first; screenshots/vision are
//! a complementary sensor, not the universal representation. Snapshots are
//! semantic projections, never DOM dumps.

pub mod alias;
pub mod diff;
pub mod filter;
pub mod fingerprint;
pub mod ids;
pub mod model;
pub mod prune;

pub use alias::{assign_aliases, AliasInput};
pub use diff::{diff_snapshots, page_fingerprint, ElementChange, SnapshotDelta};
pub use filter::{classify, Classification, ClassifyInput};
pub use fingerprint::{fingerprint, score, FingerprintSignals};
pub use fingerprint::{AMBIGUITY_MARGIN, SCORE_EXACT, SCORE_STRONG, SCORE_STRUCTURAL, SCORE_WEAK};
pub use ids::{
    BackendNodeId, BrowserSessionId, CdpSessionId, ExecutionContextId, FrameId, TabId, TargetId,
};
pub use model::{
    opt_str, stable_hash_hex, BBox, DialogSummary, FormSummary, ScrollState, SemanticElement,
    SemanticKind, SemanticSnapshot, TextBlock, TextKind, Viewport, VisibilityClass,
};
pub use prune::{prune, render_text, AgentObservation, PrunedElement, MAX_MODEL_ELEMENTS};
