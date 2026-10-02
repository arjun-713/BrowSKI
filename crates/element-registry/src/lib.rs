//! Stable semantic element references with leveled reacquisition.
//!
//! Boundary: owns [`ElementRef`] identity, multi-signal fingerprints,
//! reacquisition policy, and lifecycle/generation tracking. Does not touch
//! the browser: the observer supplies candidates + the set of alive backend
//! ids; the registry decides identity purely.
//!
//! Identity levels:
//!
//! ```text
//! 1. backendNodeId still alive
//! 2. same DOM identity (backend match in the candidate set)
//! 3. exact semantic fingerprint
//! 4. role + accessible name + form context
//! 5. structural similarity
//! 6. nearby geometry/context
//! 7. ambiguous → refuse/reobserve (never silently bind)
//! ```
//!
//! Aliases (`@submit`) are model-facing convenience assigned deterministically
//! (see `observation::alias`); the numeric [`ElementRef::id`] is the actual
//! identity.

use browser_agent_observation::{
    fingerprint::{AMBIGUITY_MARGIN, SCORE_STRONG, SCORE_STRUCTURAL, SCORE_WEAK},
    BackendNodeId, FingerprintSignals,
};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

/// Model-facing element reference: opaque numeric identity plus a
/// generation-scoped alias. Displays and serializes as the alias (`@submit`);
/// the numeric id is the actual identity.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ElementRef {
    pub id: u64,
    /// Model-facing alias (`@submit`). Serialized as `ref` (the contract
    /// name shared with elements, changes, and pruned views).
    #[serde(rename = "ref")]
    pub alias: String,
    pub generation: u64,
}

impl ElementRef {
    pub fn new(id: u64, alias: &str, generation: u64) -> Self {
        Self {
            id,
            alias: alias.to_string(),
            generation,
        }
    }

    pub fn alias_str(&self) -> &str {
        &self.alias
    }
}

impl std::fmt::Display for ElementRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.alias)
    }
}

/// One reacquisition candidate supplied by the observer. Frame identity
/// travels inside `signals.frame_path`.
#[derive(Debug, Clone)]
pub struct ReacquireCandidate {
    pub signals: FingerprintSignals,
}

/// Outcome of reacquisition: bound, gone, or ambiguous (refuse).
#[derive(Debug, Clone, PartialEq)]
pub enum ReacquireOutcome {
    /// Exactly one confident match.
    Bound { id: u64, level: u8, score: u32 },
    /// No candidate clears the floor: element is gone; reobserve.
    Gone,
    /// Two or more candidates contend: MUST NOT silently bind.
    Ambiguous { contenders: Vec<u64> },
}

#[derive(Debug, Clone)]
struct Entry {
    alias: String,
    signals: FingerprintSignals,
    fingerprint: String,
    backend: Option<BackendNodeId>,
    generation: u64,
    missed: u32,
}

/// Registry binding aliases to numeric identities across observations.
#[derive(Debug, Default)]
pub struct ElementRegistry {
    next_id: u64,
    entries: HashMap<u64, Entry>,
    alias_to_id: HashMap<String, u64>,
    generation: u64,
}

impl ElementRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    /// Advance the page/frame generation (call after navigation or major DOM
    /// change). Entries are kept but considered stale until reacquired.
    pub fn bump_generation(&mut self) {
        self.generation += 1;
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Bind a fresh element observed in the current generation. Returns its ref.
    /// Aliases must already be unique within the observation (see alias assignment).
    pub fn bind(
        &mut self,
        alias: &str,
        signals: FingerprintSignals,
        fingerprint: String,
        backend: Option<BackendNodeId>,
    ) -> ElementRef {
        self.next_id += 1;
        let id = self.next_id;
        let generation = self.generation;
        self.alias_to_id.insert(alias.to_string(), id);
        self.entries.insert(
            id,
            Entry {
                alias: alias.to_string(),
                signals,
                fingerprint,
                backend,
                generation,
                missed: 0,
            },
        );
        ElementRef::new(id, alias, generation)
    }

    pub fn lookup_alias(&self, alias: &str) -> Option<ElementRef> {
        self.alias_to_id.get(alias).map(|&id| {
            let e = &self.entries[&id];
            ElementRef::new(id, e.alias.as_str(), e.generation)
        })
    }

    /// Look up an entry by numeric id (target resolution).
    pub fn lookup_id(&self, id: u64) -> Option<ElementRef> {
        self.entries
            .get(&id)
            .map(|e| ElementRef::new(id, e.alias.as_str(), e.generation))
    }

    /// True if the ref was bound in the current generation.
    pub fn is_fresh(&self, reference: &ElementRef) -> bool {
        self.entries
            .get(&reference.id)
            .is_some_and(|e| e.generation == self.generation && e.alias == reference.alias_str())
    }

    /// Reacquire one stored element against fresh candidates.
    ///
    /// `alive_backends` is the set of backend ids the observer confirmed
    /// alive this snapshot (levels 1–2). Pure function of its inputs.
    pub fn reacquire(
        &self,
        id: u64,
        candidates: &[ReacquireCandidate],
        alive_backends: &HashSet<BackendNodeId>,
    ) -> ReacquireOutcome {
        let stored = match self.entries.get(&id) {
            Some(e) => e,
            None => return ReacquireOutcome::Gone,
        };

        // Level 1–2: backend identity.
        if let Some(backend) = stored.backend {
            if alive_backends.contains(&backend) {
                let hits: Vec<u64> = (0..candidates.len() as u64)
                    .filter(|&i| candidates[i as usize].signals.backend == Some(backend.get()))
                    .collect();
                return match hits.len() {
                    1 => ReacquireOutcome::Bound {
                        id,
                        level: 2,
                        score: 100,
                    },
                    0 => {
                        // Backend alive but not among candidates: fall through
                        // to semantic levels.
                        scored_fallback(&stored.signals, candidates, id)
                    }
                    // Same backend twice should not happen; refuse, never guess.
                    _ => ReacquireOutcome::Ambiguous { contenders: hits },
                };
            }
        }

        // Levels 3–6: scored semantic match.
        scored_fallback(&stored.signals, candidates, id)
    }

    /// Stored fingerprint for snapshot building.
    pub fn fingerprint_of(&self, id: u64) -> Option<&str> {
        self.entries.get(&id).map(|e| e.fingerprint.as_str())
    }

    /// All live entry ids (reconciliation driver).
    pub fn entry_ids(&self) -> Vec<u64> {
        let mut ids: Vec<u64> = self.entries.keys().copied().collect();
        ids.sort_unstable();
        ids
    }

    /// Stored signals for scoring.
    pub fn signals_of(&self, id: u64) -> Option<&FingerprintSignals> {
        self.entries.get(&id).map(|e| &e.signals)
    }

    /// Stored alias.
    pub fn alias_of(&self, id: u64) -> Option<&str> {
        self.entries.get(&id).map(|e| e.alias.as_str())
    }

    /// Refresh stored signals/fingerprint/backend after a successful
    /// reacquire (identity stays, evidence tracks drift).
    pub fn update_signals(
        &mut self,
        id: u64,
        signals: &FingerprintSignals,
        fingerprint: &str,
        backend: Option<BackendNodeId>,
    ) {
        if let Some(e) = self.entries.get_mut(&id) {
            e.signals = signals.clone();
            e.fingerprint = fingerprint.to_string();
            e.backend = backend;
        }
    }

    /// Drop an entry (gone or ambiguous): frees id and alias.
    pub fn remove(&mut self, id: u64) {
        if let Some(e) = self.entries.remove(&id) {
            self.alias_to_id.remove(&e.alias);
        }
    }

    /// Mark an entry seen in `generation` (post-reacquire refresh).
    pub fn refresh(&mut self, id: u64, generation: u64) {
        if let Some(e) = self.entries.get_mut(&id) {
            e.generation = generation;
            e.missed = 0;
        }
    }
}

/// Levels 3–6: scored semantic match over candidates.
fn scored_fallback(
    stored: &FingerprintSignals,
    candidates: &[ReacquireCandidate],
    id: u64,
) -> ReacquireOutcome {
    let mut scored: Vec<(u64, u32)> = candidates
        .iter()
        .enumerate()
        .map(|(i, c)| {
            (
                i as u64,
                browser_agent_observation::score(stored, &c.signals),
            )
        })
        .filter(|(_, s)| *s >= SCORE_WEAK)
        .collect();
    scored.sort_by_key(|b| std::cmp::Reverse(b.1));

    match scored.as_slice() {
        [] => ReacquireOutcome::Gone,
        [(_, s)] => ReacquireOutcome::Bound {
            id,
            level: level_for(*s),
            score: *s,
        },
        [(i1, s1), (i2, s2), ..] => {
            if s1 - s2 < AMBIGUITY_MARGIN && *s1 >= SCORE_STRUCTURAL {
                // Level 7: contenders too close — refuse.
                ReacquireOutcome::Ambiguous {
                    contenders: vec![*i1, *i2],
                }
            } else {
                ReacquireOutcome::Bound {
                    id,
                    level: level_for(*s1),
                    score: *s1,
                }
            }
        }
    }
}

fn level_for(score: u32) -> u8 {
    if score >= 100 {
        3
    } else if score >= SCORE_STRONG {
        4
    } else if score >= SCORE_STRUCTURAL {
        5
    } else {
        6
    }
}

// ReacquireOutcome::Bound carries the registry id (not the candidate index:
// candidates are observations, ids are identities).

#[cfg(test)]
mod tests {
    use super::*;
    use browser_agent_observation::fingerprint::FingerprintSignals;

    fn signals(name: &str) -> FingerprintSignals {
        FingerprintSignals {
            role: "button".into(),
            name: Some(name.into()),
            ancestry: "main>form".into(),
            frame_path: vec!["main".into()],
            ..Default::default()
        }
    }

    fn candidate(name: &str) -> ReacquireCandidate {
        ReacquireCandidate {
            signals: signals(name),
        }
    }

    #[test]
    fn bind_lookup_fresh_cycle() {
        let mut r = ElementRegistry::new();
        let reference = r.bind("@submit", signals("Submit"), "fp1".into(), None);
        assert_eq!(reference.to_string(), "@submit");
        assert_eq!(r.lookup_alias("@submit"), Some(reference.clone()));
        assert!(r.is_fresh(&reference));
        r.bump_generation();
        assert!(!r.is_fresh(&reference));
    }

    #[test]
    fn backend_identity_wins() {
        let mut r = ElementRegistry::new();
        let reference = r.bind("@go", signals("Go"), "fp".into(), Some(BackendNodeId(42)));
        let mut changed = signals("Go now");
        changed.backend = Some(42);
        let out = r.reacquire(
            reference.id,
            &[ReacquireCandidate { signals: changed }],
            &[BackendNodeId(42)].into_iter().collect(),
        );
        assert!(matches!(out, ReacquireOutcome::Bound { level: 2, .. }));
    }

    #[test]
    fn exact_fingerprint_reacquires() {
        let mut r = ElementRegistry::new();
        let reference = r.bind("@go", signals("Go"), "fp".into(), None);
        let out = r.reacquire(reference.id, &[candidate("Go")], &HashSet::new());
        assert!(matches!(out, ReacquireOutcome::Bound { level: 3, .. }));
    }

    #[test]
    fn ambiguous_contenders_refuse() {
        let mut r = ElementRegistry::new();
        let reference = r.bind("@go", signals("Continue"), "fp".into(), None);
        let out = r.reacquire(
            reference.id,
            &[candidate("Continue"), candidate("Continue")],
            &HashSet::new(),
        );
        assert!(matches!(out, ReacquireOutcome::Ambiguous { .. }));
    }

    #[test]
    fn gone_when_nothing_matches() {
        let mut r = ElementRegistry::new();
        let reference = r.bind("@go", signals("Go"), "fp".into(), None);
        let out = r.reacquire(
            reference.id,
            &[candidate("Something else entirely")],
            &HashSet::new(),
        );
        assert!(matches!(out, ReacquireOutcome::Gone));
    }
}
