# Privacy modes

BROWSKI currently defines `standard`, `privacy_first`, and `offline` policy
modes at the provider boundary.

- **Standard** passes bounded reasoning context through the local provider
  boundary. Provider calls may send task and page-derived information to the
  configured service.
- **Privacy first** applies conservative pattern-based redaction and
  request-scoped local token substitution before reasoning-provider calls.
  It recognizes common credential labels on semantic form fields as well as
  selected secret and PII patterns.
  Tokens returned in typed action text or values are restored locally before
  the action reaches the executor. Pattern matching does not detect every
  secret or personal value.
- **Offline** blocks the remote reasoning provider. Local Laya may be used for
  shadow observation only when enabled; it is not permitted to route actions.

These controls remain partial. They do not yet sanitize every possible field,
redact screenshots, provide a durable secret vault, or guarantee that all
sensitive data stays local. Vision requests are blocked in privacy-first and
offline modes. Do not use BROWSKI with sensitive data on the assumption that
privacy-first mode is a complete DLP system.

The extension does not store the OpenAI key or inject it into web pages.
Runtime logs should contain safe metadata only; avoid sharing traces that may
include page titles, URLs, or user-provided task text.

See the [threat model](../security/threat-model.md) for current residual risks.
