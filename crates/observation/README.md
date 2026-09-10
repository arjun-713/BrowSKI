# observation

Collection of browser-visible state: DOM, accessibility, layout, visibility,
forms, page metadata. Defines `SemanticSnapshot` / `SemanticElement`.

## May

- Define state shapes and (later) collect DOM/AX/layout snapshots.
- Fingerprint page state for diffing.

## May NOT

- Touch the network/transport (see `cdp`).
- Execute actions (see `executor`) or call LLMs.

Philosophy: browser-native semantics first; screenshot/vision is a
complementary sensor, not the universal representation.
See `docs/architecture/observation-model.md`.
