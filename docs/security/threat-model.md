# BROWSKI local-runtime threat model

**Status:** Initial internal review, 2026-10-06. This records controls and
gaps; it is not a security certification.

## Security boundaries

- Browser pages and their text are untrusted input. User instruction and
  runtime policy remain typed separately from page observation.
- The Rust browser core owns browser state, targets, execution, and
  deterministic verification.
- Python owns orchestration, provider policy, memory, and high-level recovery.
- The extension is a browser UI and permission broker. It does not own agent
  decisions or verification.
- Provider payloads pass through the Python `ProviderBoundary` before remote
  reasoning. `offline` blocks outbound reasoning; `privacy_first` applies
  heuristic local tokenization/redaction, including recognized credential
  labels on semantic form fields, then restores tokens only in typed action
  text/value fields after the provider responds.
- High-risk actions require graph-level confirmation; a UI response alone does
  not override runtime policy.

## Threats and controls

| Attack | Boundary | Mitigation | Residual risk |
|---|---|---|---|
| A webpage sends messages to the extension or imitates the local service | Page ↔ extension ↔ local runtime | No content script is needed for the side panel. Runtime connection must use Native Messaging in installed builds, with exact extension origin registration; development loopback transport requires an ephemeral credential, exact extension Origin, strict schema/version checks, and a loopback-only bind. | A compromised extension, native host, or local process can still control its permitted sessions. Local malware is outside the browser-page boundary. |
| A page uses prompt injection to request secrets or override the task | Untrusted page data ↔ Luna prompt | Keep user task, policy, and page observation in distinct typed fields. Label page text as untrusted in the provider instructions. Browser content cannot alter safety configuration or provider credentials. Add regression fixtures for instruction-like page text. | A model may still misinterpret page text; runtime policy, action validation, and confirmation remain necessary. |
| API key leaks through extension storage, content script, logs, or trace | Local secret store ↔ extension/provider | The side panel sends keys only over the authenticated Native Messaging channel to the local runtime. The runtime stores them in the OS keyring; it returns presence-only status. Never place secrets in content scripts, URLs, extension storage, logs, screenshots, or trace payloads. Environment variables remain an explicit operator-managed override. | Keyring availability and protection depend on the user's OS session. Environment variables may be visible to same-user diagnostics or child processes. Key rotation UX remains basic. |
| Provider request exposes private form data | Python context ↔ external provider | Central ProviderBoundary supports offline blocking and request-scoped privacy-first tokenization/redaction; token restoration is restricted to typed action text/value fields. It emits safe metadata only. Do not log outbound payloads. | Redaction is heuristic and can miss PII or alter meaning. Standard mode deliberately forwards the task context according to normal provider behavior. A model can replay a token into an action, so typed target binding and action policy remain required. |
| Screenshot contains credentials or private page data | Rust screenshot ↔ vision provider/storage | Capture only on semantic insufficiency; default to visible viewport or targeted region; include tab/generation metadata; keep data transient and bounded. Privacy-first and offline currently block vision requests; standard mode may send the transient screenshot to Luna. | Browser UI can contain sensitive text outside semantic fields; screenshot redaction is not implemented. Avoid standard-mode vision on sensitive pages and do not persist screenshots by default. |
| Browser-code escape hatch mutates the page or exfiltrates data | Runtime policy ↔ page execution context | Capability defaults disabled. Requests require purpose/reason, timeout, script/result bounds, expected schema, trace metadata, and post-execution verification. No shell, filesystem, or local process access. | Page JavaScript shares page APIs and cannot provide a strong network-isolation boundary by itself. Execution must remain disabled until the Rust runtime can enforce the approved capability set. |
| Extension spoofing, replay, or cross-tab confusion | Extension ↔ runtime session | Native host allowlists exact extension ID. Versioned messages carry correlation IDs and run/session identity; validate bounds and reject duplicate/stale requests. Attach only after user action; bind a run to its selected tab and detach on ownership loss. | Native host installation and stable extension ID must be managed correctly. Debugger attachment may conflict with DevTools or enterprise policy. |
| Malicious CDP method reaches the browser | Extension debugger proxy ↔ Rust runtime | Extension exposes only the documented command allowlist required by the browser backend. Validate method, target/session ownership, arguments, request ID, and response size. Reject unsupported domains/methods. | Chrome debugger APIs expose a subset of CDP and can change across Chrome versions; allowlist compatibility must be tested per supported version. |
| Localhost service is attacked by a web page or another process | Browser origin ↔ local service | Production uses Native Messaging instead of a listening control API. Development listeners bind only to 127.0.0.1/::1, require an unguessable ephemeral token, reject arbitrary Origin, bound messages, and authenticate each session. | Localhost tokens do not protect against same-user malware or a browser/extension compromise. DNS rebinding and CSRF protections require server-side origin and token checks, not CORS alone. |
| Sensitive state survives longer than needed | Runtime ↔ SQLite/checkpoints | Run metadata stores only run ID, timestamps, status, and counters. `browski runs clean` previews aged checkpoint deletion and requires `--apply`; running records are skipped unless `--include-running` is explicitly supplied. Writes, checkpoints, and metadata are deleted together in a transaction. | Graph checkpoints may still contain user task text. Retention is manual, and page-derived summaries can contain sensitive data; retention periods and deletion behavior must remain visible and tested. |
| Consequential action executes without informed approval | Agent graph ↔ user | Risk classification is code-controlled. Submit/send/purchase/delete/publish/security/financial actions pause at a checkpoint and require explicit approval tied to the pending action. Revalidate the target and observation generation before resuming. | Risk labels can be incomplete for unfamiliar sites; confirmation should display action, target, important values, and consequence. |
| Tab changes between decision and execution | User/extension ↔ runtime | Session ownership is explicit; do not silently select another tab. Reobserve if the semantic generation changes before execution and reject stale element references. | Navigation and user input can race with an in-flight action; runtime generation checks and post-action verification limit, but do not eliminate, that race. |

## Current implementation evidence and gaps

The existing M0–M7 foundation has typed semantic references, generation-based
staleness checks, typed actions, deterministic verification, bounded recovery,
SQLite graph checkpoints, and a high-risk confirmation interrupt. The
ProviderBoundary now has focused tests for privacy-first tokenization, local
restoration into typed action values, offline blocking, and context bounds.

The extension service, authenticated Native Messaging host, attached-browser
backend, vision routing for attached browsers, OS keyring integration, and
retention cleanup have implementation work in this checkout, but still need
packaged extension and end-to-end evidence. End-to-end secret-leak tests are
not yet complete.
The browser-code execution route remains disabled until a restricted evaluator
can enforce its capabilities. Do not describe these gaps as mitigated merely
because this document lists a planned control.

## Review cadence

Revisit this document when the extension protocol, provider boundary,
credential store, screenshot path, browser-code capability, persistence
format, or action-risk policy changes. Security claims require implementation
and regression-test evidence at the boundary described here.
