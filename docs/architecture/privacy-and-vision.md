# Privacy and vision (modular; partial implementation)

**Status:** Bounded viewport screenshot capture and structured Luna vision are
wired as an optional on-demand path. The agent invokes vision only when a task
explicitly requires visual information that browser-native semantics do not
provide. Visual findings are advisory text and semantic refs; Luna still picks
from bounded browser actions. Vision is disabled by default and blocked in
privacy-first/offline modes until screenshot redaction exists. Text redaction
remains heuristic. Privacy-first reasoning uses a temporary in-memory token
vault for one provider request and restores tokens only in typed action text
and values before local execution. The visual finding travels in a typed
`visual_observation` field and Luna treats it as untrusted page evidence.

The routing decision is recorded in
[ADR-009](../decisions/ADR-009-on-demand-vision-fallback.md).
The outbound privacy contract is recorded in
[ADR-010](../decisions/ADR-010-outbound-provider-privacy-boundary.md).

Privacy and local visual perception are important capabilities, but they are
**modular, not mandatory for every action**. The default grounding path is
browser-native semantics (DOM + accessibility + layout); screenshots and
local perception attach where they add value without weakening general
browser intelligence.

## Implemented storage and remaining modules

API credentials use a local OS-keyring abstraction or an explicit environment
override. There is no plaintext-file fallback for API keys. This store is
separate from the transient privacy token vault. Durable LangGraph SQLite
checkpoint values use authenticated encryption; see
[privacy architecture](privacy.md) and
[ADR-015](../decisions/ADR-015-encrypted-checkpoints.md).

- **Local PII detector / secret detector** — broader coverage than the current
  pattern-based detection of common PII and secret formats. The current
  provider boundary also recognizes common credential labels on semantic form
  fields such as password and access-token inputs.
- **Durable token vault** — privacy tokens are transient and request-scoped;
  multi-request private-value restoration is not promised.
- **Sanitized screenshots** — redaction pass before any image leaves the host.
- **Local visual parser** — small on-device model for grounding when AX/DOM
  is insufficient (canvas, custom widgets).

## Constraints

- Privacy filtering must not silently degrade task capability: redactions are
  recorded as evidence so verification and debugging stay honest.
- Token restoration is limited to typed action `text` and `value` fields and
  happens after the reasoning provider returns. It does not make the current
  heuristic detector a complete data-loss prevention system.
- The old SIH-style *mandatory* pipeline (screenshot → local detector → OCR →
  ScreenGraph → privacy → remote LLM → executor for every step) is explicitly
  **not** the default architecture. Its ideas reappear only as the optional
  modules above.
- CAPTCHAs and equivalent challenges are reported to the user, never bypassed.
