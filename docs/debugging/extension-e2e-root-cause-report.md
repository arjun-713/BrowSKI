# Extension execution root-cause report

Status: attached observation failure repaired and checked on the user's Google
tab. Broader autonomous task acceptance remains in progress.

## Established failure boundary

The earlier user runs failed in first semantic observation before providers
or actions. After that repair, a later run reached the local provider boundary
and hit the request-size limit; no API request was sent. The crowded-page
extension regression then exposed the separate connection lifetime limit.
See the
[incident record](extension-step-zero-incident.md) and the complete
[execution-path audit](extension-execution-path-audit.md).

## Confirmed contributing defects

| Defect | Responsible boundary | Corrective work |
| --- | --- | --- |
| Native error flattened to RuntimeError text | Rust/PyO3 | Preserve reviewed native category, operation, recoverability and CDP code; no private message |
| No observation-start event | Graph/telemetry | Emit before awaiting Rust |
| Attachment/runtime IDs disagree | Service/runtime | Explicit consistent correlation identities |
| Two terminal rows for one failure | Runtime result/timeline | Preserve result and failure evidence with one terminal presentation |
| Doctor equates socket files with availability | CLI/service | Authenticated read-only live integration probes |
| Valid nested DOM rejected at JSON depth 128 | Rust extension transport | Bounded stack-safe parsing; safe errors propagated to pending requests |
| Old bundle rejects new diagnostic event types | Extension protocol | Rebuilt 0.1.6; ignore bounded unknown trace kinds; disconnect malformed authoritative messages |
| Full semantic inventory exceeds 32,000-character provider limit | Provider boundary | Project relevant state while preserving task policy, typed candidates and evidence; report irreducible size errors accurately |
| Connection closes after 4,096 browser messages | Extension/runtime protocol | Sequenced v1 envelopes in 0.1.7 with bounded recent UUID retention and old-packet rejection |
| Registry backend identity is overridden by a second semantic scan | Rust observation | Bind the unique live backend directly; keep semantic fallback and ambiguity refusal |
| Installed source runtime uses a development binding | Packaging | Installer builds optimized release binaries; developer commands retain their development profile |

The user's Google tab passed a basic CDP probe but failed DOM observation with
`CONNECTION_LOST`. An 80-wrapper local page reproduced this through the packaged
extension: a 171-level JSON response exceeded the default 128-level parser
limit. The reader discarded that error. After the bounded parser repair, the
same extension-driven local task passes and the user's Google DOM observation
passes. See the incident record for evidence and the distinction between this
failure and the older bundle's protocol timeout.

The later fixes passed permanent real-extension deep/crowded regressions and
three bounded live Luna runs. The same live crowded-page task improved from
90.293 seconds to 41.444 seconds after the identity fix and completed in
35.608 seconds with the final release binding. Each run used one model call.
These are smoke measurements; crowded-page latency and broader task reliability
remain limitations. All detailed outputs and gate results are in the ledger.

The differential suite also exposes a remaining ownership limitation: a page
`target="_blank"` click creates a tab outside the attached session's registry.
Managed mode discovers it; attached mode cannot activate it. Explicit runtime
`new_tab` actions use the authenticated owned-tab path and are supported. The
failing click-created-tab case remains recorded; unrelated browser tabs must
not be adopted to make a test pass.

## Preserved boundaries

The extension remains a debugger proxy and product surface. Rust owns all
semantic observation, target identity, execution and verification. The work does
not replace the browser backend or weaken authentication, origin consent,
owned-tab bounds, approval, stale-target checks, checkpoint sanitation or
provider policy.

## Validation and remaining work

See the [validation ledger](extension-e2e-validation-report.md). Existing benchmark
success is managed-browser evidence and is reported separately from actual
extension transport tests. No universal or 24/24 reliability claim is justified.
