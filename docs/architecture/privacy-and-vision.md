# Privacy and vision (future, modular)

Privacy and local visual perception are important capabilities, but they are
**modular, not mandatory for every action**. The default grounding path is
browser-native semantics (DOM + accessibility + layout); screenshots and
local perception attach where they add value without weakening general
browser intelligence.

## Planned modules (Milestone 7/10)

- **Local PII detector / secret detector** — flag sensitive values in
  observations before they reach a remote model.
- **Token vault** — secrets referenced by token; the model sees `@secret:3`,
  the executor substitutes at fill time. The browser core never logs values.
- **Sanitized screenshots** — redaction pass before any image leaves the host.
- **Local visual parser** — small on-device model for grounding when AX/DOM
  is insufficient (canvas, custom widgets).

## Constraints

- Privacy filtering must not silently degrade task capability: redactions are
  recorded as evidence so verification and debugging stay honest.
- The old SIH-style *mandatory* pipeline (screenshot → local detector → OCR →
  ScreenGraph → privacy → remote LLM → executor for every step) is explicitly
  **not** the default architecture. Its ideas reappear only as the optional
  modules above.
- CAPTCHAs and equivalent challenges are reported to the user, never bypassed.
