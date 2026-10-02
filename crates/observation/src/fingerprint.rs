//! Multi-signal element fingerprints.
//!
//! Identity is a multi-signal problem from day one. CSS selectors are never
//! identity. A fingerprint combines role, names, labels, form context,
//! ancestry, frame, and stable attributes; volatile signals (geometry,
//! backend node ids) participate in *scoring*, not in the stable hash.
//!
//! Reacquisition levels (implemented in `element-registry`):
//!
//! ```text
//! 1. backendNodeId still alive        (browser-checked, exact)
//! 2. same DOM identity                (backend match in candidate set)
//! 3. exact semantic fingerprint       (score 100)
//! 4. role + accessible name + context (score >= 80)
//! 5. structural similarity            (score >= 60)
//! 6. nearby geometry/context          (score >= 40)
//! 7. ambiguous → refuse/reobserve     (top-2 within margin)
//! ```

use crate::model::stable_hash_hex;
use serde::{Deserialize, Serialize};

/// Score cutoffs for reacquisition levels 3–6.
pub const SCORE_EXACT: u32 = 100;
pub const SCORE_STRONG: u32 = 80;
pub const SCORE_STRUCTURAL: u32 = 60;
pub const SCORE_WEAK: u32 = 40;
/// Top-two margin below which a match is ambiguous (level 7: refuse).
pub const AMBIGUITY_MARGIN: u32 = 10;

/// Normalized identity signals for one element.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct FingerprintSignals {
    pub role: String,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(default)]
    pub input_name: Option<String>,
    #[serde(default)]
    pub placeholder: Option<String>,
    #[serde(default)]
    pub input_type: Option<String>,
    #[serde(default)]
    pub nearby: Option<String>,
    #[serde(default)]
    pub ancestry: String,
    #[serde(default)]
    pub frame_path: Vec<String>,
    /// Bucketed geometry (`WxH@X,Y` on a coarse grid; volatile by design).
    #[serde(default)]
    pub geometry: String,
    #[serde(default)]
    pub backend: Option<i64>,
    /// Stable attributes only (e.g. `data-testid`).
    #[serde(default)]
    pub stable_attrs: Vec<(String, String)>,
    /// Form/section context, e.g. `billing`, `shipping`.
    #[serde(default)]
    pub context: Option<String>,
}

pub fn norm(s: &str, max: usize) -> String {
    let collapsed = s.split_whitespace().collect::<Vec<_>>().join(" ");
    let lower = collapsed.to_lowercase();
    if lower.len() > max {
        lower[..max].to_string()
    } else {
        lower
    }
}

fn opt(s: &Option<String>, max: usize) -> String {
    s.as_deref().map(|v| norm(v, max)).unwrap_or_default()
}

/// Stable fingerprint: every signal EXCEPT backend id, geometry (both
/// volatile across renders), and raw text (content churns inside anonymous
/// containers; text still participates in *scoring*). Two elements with
/// equal fingerprints are the same control for level-3 reacquisition.
pub fn fingerprint(signals: &FingerprintSignals) -> String {
    let mut attrs = signals.stable_attrs.clone();
    attrs.sort();
    let attr_str = attrs
        .iter()
        .map(|(k, v)| format!("{k}={}", norm(v, 60)))
        .collect::<Vec<_>>()
        .join(";");
    let canonical = format!(
        "{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
        norm(&signals.role, 40),
        opt(&signals.name, 80),
        opt(&signals.label, 80),
        opt(&signals.input_name, 60),
        opt(&signals.placeholder, 80),
        opt(&signals.input_type, 30),
        opt(&signals.nearby, 120),
        norm(&signals.ancestry, 200),
        signals.frame_path.join(">"),
        attr_str,
        opt(&signals.context, 60),
    );
    stable_hash_hex(&canonical)
}

/// Weighted similarity score 0–100 between stored and candidate signals.
///
/// Weights reflect discriminative power: exact name matches dominate,
/// geometry only nudges. Deterministic: same inputs, same score.
pub fn score(stored: &FingerprintSignals, candidate: &FingerprintSignals) -> u32 {
    if fingerprint(stored) == fingerprint(candidate) {
        return SCORE_EXACT;
    }
    let mut total = 0u32;
    // Role must agree for any non-trivial score (different roles = different controls).
    if norm(&stored.role, 40) != norm(&candidate.role, 40) {
        return total;
    }
    total += 10;
    if !stored.name.as_deref().unwrap_or("").is_empty()
        && opt(&stored.name, 80) == opt(&candidate.name, 80)
    {
        total += 35;
    }
    if !stored.text.as_deref().unwrap_or("").is_empty()
        && opt(&stored.text, 120) == opt(&candidate.text, 120)
    {
        total += 15;
    }
    if !stored.label.as_deref().unwrap_or("").is_empty()
        && opt(&stored.label, 80) == opt(&candidate.label, 80)
    {
        total += 10;
    }
    if !stored.input_name.as_deref().unwrap_or("").is_empty()
        && opt(&stored.input_name, 60) == opt(&candidate.input_name, 60)
    {
        total += 10;
    }
    // Tag agreement keeps unnamed structural elements (forms, regions)
    // stable across benign ancestor churn.
    if !stored.input_type.as_deref().unwrap_or("").is_empty()
        && opt(&stored.input_type, 30) == opt(&candidate.input_type, 30)
    {
        total += 8;
    }
    if !stored.placeholder.as_deref().unwrap_or("").is_empty()
        && opt(&stored.placeholder, 80) == opt(&candidate.placeholder, 80)
    {
        total += 8;
    }
    if opt(&stored.context, 60) == opt(&candidate.context, 60)
        && !stored.context.as_deref().unwrap_or("").is_empty()
    {
        total += 7;
    }
    if stored.frame_path == candidate.frame_path {
        total += 5;
    }
    if norm(&stored.ancestry, 200) == norm(&candidate.ancestry, 200) && !stored.ancestry.is_empty()
    {
        total += 5;
    }
    if !stored.geometry.is_empty() && stored.geometry == candidate.geometry {
        total += 3;
    }
    if !stored.nearby.as_deref().unwrap_or("").is_empty()
        && opt(&stored.nearby, 120) == opt(&candidate.nearby, 120)
    {
        total += 2;
    }
    total.min(99)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn signals(name: &str) -> FingerprintSignals {
        FingerprintSignals {
            role: "button".into(),
            name: Some(name.into()),
            ancestry: "main>form".into(),
            frame_path: vec!["main".into()],
            ..Default::default()
        }
    }

    #[test]
    fn fingerprint_stable_and_volatile_insensitive() {
        let mut a = signals("Continue");
        let mut b = signals("continue ");
        a.backend = Some(1);
        b.backend = Some(999);
        a.geometry = "10x10@0,0".into();
        b.geometry = "800x600@5,5".into();
        assert_eq!(fingerprint(&a), fingerprint(&b));
        assert_eq!(score(&a, &b), SCORE_EXACT);
    }

    #[test]
    fn text_churn_does_not_break_identity() {
        // Anonymous containers change text constantly; identity must not.
        let a = FingerprintSignals {
            role: "generic".into(),
            ancestry: "main".into(),
            frame_path: vec!["main".into()],
            text: Some("Count: 0".into()),
            ..Default::default()
        };
        let mut b = a.clone();
        b.text = Some("Count: 1".into());
        assert_eq!(fingerprint(&a), fingerprint(&b));
        // ...but text still separates genuinely different nodes in scoring.
        let mut c = a.clone();
        c.text = Some("Something entirely different here".into());
        c.name = Some("x".into());
        let mut d = a.clone();
        d.name = Some("y".into());
        assert!(score(&c, &d) < score(&a, &b));
    }

    #[test]
    fn score_separates_same_role_from_same_control() {
        let stored = signals("Continue");
        let same = signals("Continue");
        let mut other = signals("Cancel");
        other.ancestry = "main>form".into();
        other.frame_path = vec!["main".into()];
        assert!(score(&stored, &same) >= SCORE_STRONG);
        assert!(score(&stored, &other) < SCORE_STRUCTURAL);
    }

    #[test]
    fn role_mismatch_scores_zero() {
        let mut a = signals("Continue");
        let mut b = signals("Continue");
        a.role = "button".into();
        b.role = "link".into();
        assert_eq!(score(&a, &b), 0);
    }
}
