//! Visibility and interactability classification (pure functions).
//!
//! `display != none` is nowhere near enough. Classification combines DOM
//! state, computed style, bounding box, viewport intersection,
//! pointer-events, disabled/inert flags, and hit-test results. The CDP calls
//! that produce these inputs live in `browser-core`'s observer; everything
//! here is deterministic and unit-testable.
//!
//! Classes: `VISIBLE / HIDDEN / OFFSCREEN / OCCLUDED`, plus the `enabled`
//! and `interactable` flags (`DISABLED / INERT / READ_ONLY /
//! NON_INTERACTIVE / INTERACTIVE` in model-facing terms).

use crate::model::{BBox, Viewport, VisibilityClass};

/// Inputs for one classification decision.
#[derive(Debug, Clone, Default)]
pub struct ClassifyInput {
    /// Zero-area or missing box.
    pub has_box: bool,
    pub bbox: BBox,
    pub viewport: Viewport,
    /// Computed `display` (lowercase, e.g. `block`, `none`).
    pub display: String,
    /// Computed `visibility` (lowercase).
    pub visibility_css: String,
    /// Computed `opacity` 0.0–1.0.
    pub opacity: f64,
    /// Computed `pointer-events` (lowercase).
    pub pointer_events: String,
    /// AX/framework disabled, or `disabled` attribute.
    pub disabled: bool,
    /// `inert` attribute or inert ancestor.
    pub inert: bool,
    /// Whether the element's hit-test point resolves to itself or a
    /// descendant (i.e. nothing foreign covers it).
    pub hit_test_pass: bool,
    /// Readonly controls focus but never change state: visible, never
    /// interactable.
    pub readonly: bool,
    /// Semantic actionability (button/link/input/... or AX actionable).
    pub actionable: bool,
}

/// Outcome of classification.
#[derive(Debug, Clone, PartialEq)]
pub struct Classification {
    pub visibility: VisibilityClass,
    pub visible: bool,
    pub enabled: bool,
    pub interactable: bool,
}

/// Classify visibility and interactability.
///
/// Rules (in order):
/// 1. No box, `display: none`, `visibility: hidden/collapse`, or opacity
///    ~0 → `HIDDEN` (never exposed as interactable).
/// 2. Disabled or inert → still classified by geometry, but `enabled=false`,
///    `interactable=false`.
/// 3. Box entirely outside the viewport → `OFFSCREEN` (`visible=true` — it
///    is rendered — but `interactable=false`: a scroll is required first).
/// 4. Hit test fails → `OCCLUDED`, `interactable=false`.
/// 5. `pointer-events: none` → not interactable (still visible).
/// 6. Otherwise `VISIBLE`; `interactable = actionable`.
pub fn classify(input: &ClassifyInput) -> Classification {
    let hidden = !input.has_box
        || input.bbox.is_empty()
        || input.display == "none"
        || input.visibility_css == "hidden"
        || input.visibility_css == "collapse"
        || input.opacity < 0.05;
    if hidden {
        return Classification {
            visibility: VisibilityClass::Hidden,
            visible: false,
            enabled: !input.disabled && !input.inert,
            interactable: false,
        };
    }

    let enabled = !input.disabled && !input.inert;

    // Viewport intersection (CSS pixels, main-frame viewport).
    let intersects = input.bbox.x < input.viewport.width
        && input.bbox.y < input.viewport.height
        && input.bbox.x + input.bbox.width > 0.0
        && input.bbox.y + input.bbox.height > 0.0;
    if !intersects {
        return Classification {
            visibility: VisibilityClass::Offscreen,
            visible: true,
            enabled,
            interactable: false,
        };
    }

    if !input.hit_test_pass {
        return Classification {
            visibility: VisibilityClass::Occluded,
            visible: true,
            enabled,
            interactable: false,
        };
    }

    let pointer_ok = input.pointer_events != "none";
    Classification {
        visibility: VisibilityClass::Visible,
        visible: true,
        enabled,
        interactable: enabled && pointer_ok && input.actionable && !input.readonly,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn visible_input() -> ClassifyInput {
        ClassifyInput {
            has_box: true,
            bbox: BBox {
                x: 10.0,
                y: 10.0,
                width: 100.0,
                height: 30.0,
            },
            viewport: Viewport {
                width: 1280.0,
                height: 800.0,
                device_scale_factor: 1.0,
            },
            display: "block".into(),
            visibility_css: "visible".into(),
            opacity: 1.0,
            pointer_events: "auto".into(),
            hit_test_pass: true,
            actionable: true,
            ..Default::default()
        }
    }

    #[test]
    fn happy_path_is_interactive() {
        let c = classify(&visible_input());
        assert_eq!(c.visibility, VisibilityClass::Visible);
        assert!(c.visible && c.enabled && c.interactable);
    }

    #[test]
    fn display_none_is_hidden() {
        let mut i = visible_input();
        i.display = "none".into();
        let c = classify(&i);
        assert_eq!(c.visibility, VisibilityClass::Hidden);
        assert!(!c.visible && !c.interactable);
    }

    #[test]
    fn zero_opacity_is_hidden() {
        let mut i = visible_input();
        i.opacity = 0.0;
        assert_eq!(classify(&i).visibility, VisibilityClass::Hidden);
    }

    #[test]
    fn offscreen_is_rendered_but_not_interactable() {
        let mut i = visible_input();
        i.bbox.y = 5000.0;
        let c = classify(&i);
        assert_eq!(c.visibility, VisibilityClass::Offscreen);
        assert!(c.visible && !c.interactable);
    }

    #[test]
    fn occluded_is_not_interactable() {
        let mut i = visible_input();
        i.hit_test_pass = false;
        let c = classify(&i);
        assert_eq!(c.visibility, VisibilityClass::Occluded);
        assert!(!c.interactable);
    }

    #[test]
    fn disabled_kills_interactability() {
        let mut i = visible_input();
        i.disabled = true;
        let c = classify(&i);
        assert!(!c.enabled && !c.interactable);
        assert_eq!(c.visibility, VisibilityClass::Visible);
    }

    #[test]
    fn pointer_events_none_blocks_action() {
        let mut i = visible_input();
        i.pointer_events = "none".into();
        assert!(!classify(&i).interactable);
    }

    #[test]
    fn readonly_is_visible_but_not_interactable() {
        let mut i = visible_input();
        i.readonly = true;
        let c = classify(&i);
        assert!(c.visible && c.enabled && !c.interactable);
    }

    #[test]
    fn non_actionable_is_exposed_but_not_interactive() {
        let mut i = visible_input();
        i.actionable = false;
        let c = classify(&i);
        assert!(c.visible && !c.interactable);
    }
}
