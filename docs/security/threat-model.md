# BROWSKI local-runtime threat model

**Status:** Internal productization review, 2026-10-08. This records controls and
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
  text/value fields after the provider responds. The recognized textual token
  patterns cover selected common formats; this is not universal secret
  detection.
- High-risk actions require graph-level confirmation; a UI response alone does
  not override runtime policy.

## Threats and controls

| Attack | Boundary | Mitigation | Residual risk |
|---|---|---|---|
| A webpage sends messages to the extension or imitates the local service | Page ↔ extension ↔ local runtime | No content script is needed for the side panel. Runtime connection must use Native Messaging in installed builds, with exact extension origin registration; development loopback transport requires an ephemeral credential, exact extension Origin, strict schema/version checks, and a loopback-only bind. | A compromised extension, native host, or local process can still control its permitted sessions. Local malware is outside the browser-page boundary. |
| A page uses prompt injection to request secrets or override the task | Untrusted page data ↔ Luna prompt | Keep user task, policy, and page observation in distinct typed fields. Label page text as untrusted in the provider instructions. Browser content cannot alter safety configuration or provider credentials. Add regression fixtures for instruction-like page text. | A model may still misinterpret page text; runtime policy, action validation, and confirmation remain necessary. |
| API key leaks through extension storage, content script, logs, or trace | Local secret store ↔ extension/provider | The side panel sends keys only over the authenticated Native Messaging channel to the local runtime. The runtime stores them in the OS keyring; it returns presence-only status. Never place secrets in content scripts, URLs, extension storage, logs, screenshots, or trace payloads. Environment variables remain an explicit operator-managed override. | Keyring availability and protection depend on the user's OS session. Environment variables may be visible to same-user diagnostics or child processes. Key rotation UX remains basic. |
| Provider request exposes private form data | Python context ↔ external provider | Central ProviderBoundary supports offline blocking and request-scoped privacy-first tokenization/redaction; token restoration is restricted to typed action text/value fields. It emits safe metadata only. Do not log outbound payloads. | Redaction is heuristic and can miss PII or alter meaning. Standard mode deliberately forwards the task context according to normal provider behavior. A model can replay a token into an action, so typed target binding and action policy remain required. |
| Screenshot contains credentials or private page data | Rust screenshot ↔ vision provider/storage | Capture only on semantic insufficiency; the implemented path captures the visible viewport with tab/generation metadata and keeps data transient and bounded. Privacy-first and offline currently block vision requests; standard mode may send the transient screenshot to Luna. | Browser UI can contain sensitive text outside semantic fields; screenshot redaction and targeted-region capture are not implemented. Avoid standard-mode vision on sensitive pages and do not persist screenshots by default. |
| Browser-code escape hatch mutates the page or exfiltrates data | Runtime policy ↔ isolated QuickJS runtime | Capability defaults disabled. Fresh runtime receives only a bounded Rust semantic projection; no DOM/browser/network/filesystem/process callbacks exist. Source, timeout, heap, stack and result bounds, schema validation, safe paired traces and fresh-state checks are enforced. | Engine vulnerabilities and denial of service within the configured resource budget remain possible. This is a local semantic-data transform, not a general page-code sandbox. Live-page model code remains disabled. |
| Extension spoofing, replay, or cross-tab confusion | Extension ↔ runtime session | Native host allowlists exact extension ID. Versioned messages carry correlation IDs and run/session identity; validate bounds and reject duplicate/stale requests. Attach only after user action; bind a run to its selected tab and detach on ownership loss. | Native host installation and stable extension ID must be managed correctly. Debugger attachment may conflict with DevTools or enterprise policy. |
| Prompt injection or sensitive text copied during an explicit transfer | Browser page text → Luna and typed form candidate | Page data is framed as untrusted evidence. A narrow user grammar names the exact source and destination; runtime validates a current visible semantic ref, rejects recognized sensitive labels/patterns, and permits only a finite value for one uniquely named input while the source tab is owned. | Prompt wording is not a security boundary. Pattern recognition is incomplete; standard mode can send the user-authorized value to the configured provider. The transfer feature is not a universal DLP control. |
| Malicious CDP method reaches the browser | Extension debugger proxy ↔ Rust runtime | Extension exposes only the documented command allowlist required by the browser backend. Validate method, target/session ownership, arguments, request ID, and response size. Reject unsupported domains/methods. | Chrome debugger APIs expose a subset of CDP and can change across Chrome versions; allowlist compatibility must be tested per supported version. |
| Localhost service is attacked by a web page or another process | Browser origin ↔ local service | The implemented transport uses Native Messaging and an owner-only authenticated Unix relay, with no HTTP control listener. Any future development HTTP listener must bind only to loopback, require an ephemeral token, reject arbitrary Origin, bound messages and authenticate each session. | The Unix relay and any future loopback token do not protect against same-user malware or browser/extension compromise. A future HTTP transport would also need server-side rebinding/CSRF protections. |
| Sensitive state survives longer than needed | Runtime ↔ SQLite/checkpoints | Durable checkpoint values and pending writes use authenticated AES-GCM encryption; a read-only preflight rejects plaintext or unsupported rows before saver setup or writes. The key is held in the OS keyring where available, with a private owner-only file fallback shared by this installation for the current user. Run metadata stores only bounded run IDs, timestamps, status, and typed aggregate counters. Those counters include action attempts, failed verifications, recoveries, browser-code calls, vision calls, Luna call/effort counts, and Laya shadow decisions; duration is elapsed wall time across pauses and restarts, not active time. `browski runs clean` previews aged checkpoint deletion and requires `--apply`; running records are skipped unless `--include-running` is explicitly supplied. Writes, checkpoints, run metadata, and metric rows are deleted together in a transaction. | SQLite metadata remains separate and must not contain user text. Custom run IDs are plaintext bounded slugs, not secret-scanned. The file fallback is accessible to the same user account and does not protect against same-user compromise. Losing or mismatching the key makes checkpoints unavailable; startup fails closed rather than replacing it. Retention is manual and deletes rows logically; SQLite free pages, WAL files, snapshots, and backups may retain old bytes. |
| Consequential action executes without informed approval | Agent graph ↔ user | Risk classification is code-controlled. Recognized submit/send/purchase/delete/publish/security/financial actions, common order/payment/donation/subscription labels, and account/security modification controls pause at a checkpoint and require explicit approval tied to the pending action. Revalidate the target and observation generation before resuming. | This is a bounded label and form heuristic, not a universal consequence detector. Unfamiliar or misleading labels and unlabeled controls may still be classified medium risk and execute without explicit approval; confirmation should display action, target, important values, and consequence. |
| Tab changes between decision and execution | User/extension ↔ runtime | Session ownership is explicit; do not silently select another tab. Reobserve if the semantic generation changes before execution and reject stale element references. | Navigation and user input can race with an in-flight action; runtime generation checks and post-action verification limit, but do not eliminate, that race. |

## Current implementation evidence and gaps

The 2026-10-15 consent review added a conservative gate for explicitly requested
approval. Recognized requests such as “get my confirmation” require approval
for click, keypress, dialog and tab-close operations even when a neutral label
does not reveal the consequence. This also overrides a disabled general
high-risk confirmation setting. It can ask for approval earlier than the final
operation; the grammar and consequence detector remain bounded. Real Chromium
regressions cover neutral and consequential labels, approval and denial.

Cross-page recording reads a currently visible source reference before returning
to its registered destination. The stored value is a snapshot fact. Background
source changes after capture are not continuously revalidated, so these values
must not be described as guaranteed current data. Comparing live prices or
other volatile facts still requires task-level reinspection. Source ownership,
explicit user intent and current destination binding remain required.

The existing M0–M7 foundation has typed semantic references, generation-based
staleness checks, typed actions, deterministic verification, bounded recovery,
encrypted SQLite graph checkpoints, and a high-risk confirmation interrupt. The
ProviderBoundary now has focused tests for privacy-first tokenization,
selected provider token formats and credential labels, a page-injection string
containing a recognized secret pattern, local restoration into typed action
values, offline blocking, and context bounds. These tests establish specific
behavior only; they do not establish general injection resistance or complete
secret detection.

Real packaged-Chromium tests exercise the native host and authenticated service,
attached Rust observation/execution/verification, task controls, confirmation
denial and cancellation on tab/host loss. Native side-panel creation is tested
using Chrome's API with a synthetic user gesture. User actions in UI tests use
the packaged panel page. Provider decisions are fixtures; live Luna behavior
is not established by these tests. The isolated semantic-data transform has
engine and graph tests for capability gating and transient output.

Screenshot redaction, universal PII detection, general prompt-injection
resistance, browser-store distribution and independent security review remain
unavailable. Same-user malware can access a running process and the private
fallback files; local process isolation is not a defense against account
compromise. This review does not certify the product.

Completion checks prove the configured effects and recognized user constraints;
they do not prove that a model's plan contains every obligation in an arbitrary
natural-language task. Explicit plan revisions remain model-authored. A
`task_complete` proposal cannot rewrite initialized proof, and a previous
approval never authorizes the next affected mutation. The task-level approval
receipt is not a semantic proof that a particular final requested effect
occurred. Omitted-work regressions require independent task-level evaluation.

## Review cadence

Revisit this document when the extension protocol, provider boundary,
credential store, screenshot path, browser-code capability, persistence
format, or action-risk policy changes. Security claims require implementation
and regression-test evidence at the boundary described here.
