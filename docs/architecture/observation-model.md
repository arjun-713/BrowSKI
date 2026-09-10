# Observation model (M2 implemented)

## Philosophy

**DOM + accessibility + layout + browser state first. Screenshot/vision when
required.** The snapshot is NOT a serialized DOM dump: it is a compact,
stable, model-friendly projection. The agent sees:

```text
@search_box
  textbox
  "Search jobs"

@location
  combobox
  value="Bengaluru"

@apply
  button
  "Apply"
```

instead of thousands of nodes. No OCR/VLM in M2 by decision: if ordinary
browser-native controls are misrepresented, vision hides structural problems.

## Pipeline

```text
CDP DOM + Accessibility + layout
        ↓
raw page graph (frame/shadow-aware walk)
        ↓
visibility/interactability filtering
        ↓
semantic labeling (AX-enriched)
        ↓
ElementRegistry (leveled reacquisition)
        ↓
stable semantic refs
        ↓
SemanticSnapshot → incremental diff
```

Collection (`browser-core/src/observer.rs`): one `getFullAXTree` +
`getDocument(depth:-1, pierce:true)` + `getLayoutMetrics` concurrently, then
per-candidate geometry (`getBoxModel`, computed style, `getNodeForLocation`
with a JS `contains()` fallback for text-node hits). Output order is document
order — deterministic: identical pages yield identical snapshots.

## Merge rule

```text
DOM node + AX node + layout node + form state → SemanticElement
```

So `<div class="x91" onclick>` with accessible name "Continue" arrives as
`role=button name="Continue" interactable=true`. AX enriches (role, name,
value, states); DOM gives structure/attributes/frames/shadow; layout gives
boxes and hit-testing.

## Identity

Multi-signal fingerprints (role, names, labels, form context, ancestry,
frame, stable attrs; geometry/backend score but never hash). Reacquisition
levels 1–7 (backend alive → DOM identity → exact fingerprint → role+name →
structural → nearby → refuse). Ambiguous contenders never silently bind.
Aliases (`@email`, `@billing_continue`) are deterministic model convenience;
the numeric registry id is the identity. Full design: ADR-003.

## Visibility

Classes `VISIBLE / HIDDEN / OFFSCREEN / OCCLUDED` plus `enabled` and
`interactable` flags (`DISABLED / INERT / READ_ONLY / NON_INTERACTIVE /
INTERACTIVE` in model terms). Clickability combines DOM state, computed
style, box, viewport intersection, pointer-events, disabled/inert, and hit
testing. Readonly focuses but never interacts; offscreen renders but needs a
scroll first.

## Frames and shadow DOM

Frames are first-class: `frame_path` provenance (`main → iframe[checkout]`),
never flattened without provenance. Open shadow roots are pierced (ancestry
records the `>>shadow` boundary); closed roots degrade gracefully (absent,
never garbage). Cross-origin iframe *contents* are out of scope in M2
(documented follow-up: per-frame AX collection); the frame element itself
still appears.

## Two representations

- `SemanticSnapshot`: everything (elements, text blocks, forms, dialogs,
  focus, fingerprints, generations).
- `AgentObservation`: pruned deterministically (interactables, headings,
  dialogs, alerts, tables, nav, changed/memory refs; 300 cap with marker)
  and renderable to `@ref` text. No LLM decides what the LLM sees.

## Deltas and fingerprints

`SnapshotDelta { added, removed, changed, moved, navigation_changed,
focus_changed }` matches by fingerprint, so a form fill arrives as
`~ @state value: "" → "Karnataka"` instead of a full resnapshot. Page
fingerprints hash stable signals (URL, headings, element structure, forms,
text) — never raw HTML — and double as stagnation input later.

## Known limits (M2 → M3+)

- OOPIF contents, computed-style edge cases beyond the classified set,
  virtualized-list windowing (offscreen items listed, not windowed),
  form-control grouping by explicit `<form>` ancestry only.
