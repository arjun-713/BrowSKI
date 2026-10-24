# Extension execution root-cause report

Scope: this investigation concerns the explicit **Legacy attached-browser**
path. The current General/Fast migration and its managed-browser results are
described in [the active plan](../../ARCHITECTURE_PLAN.md); they do not prove
that an attached personal Chrome tab works.

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


## October 22: additional reproduced lifecycle failures

The existing `mango` checkout was explicitly selected by the user; the path
named `Browski` in the original brief still does not exist. The current branch
is `migration/browski-v2`, based on `5b6113d`. Pre-existing uncommitted
source-transfer work is outside this repair and is preserved.

### Observation retry waits on its own registry lock

The complete Rust gate stalled in `stress_runtime`. Inspection found that
`observe_full_attempt` retained the registry write guard after assigning element
identities. If the browser generation changed during collection, its bounded
recursive fresh attempt tried to acquire the same registry lock. Network
command timeouts cannot resolve a wait on that lock.

A deterministic test through `BrowserSession::from_attached_transport` injects
a generation change during `DOM.getDocument`. Before the fix it fails with
`Elapsed(())` at its one-second bound. The observer now drops the completed
binding guard before subsequent awaits. The same test passes and proves both
one successful retry and refusal after a second navigation change; each case
performs exactly two collections. A subsequent observation remains usable.
No stale-generation fence, ambiguity check or retry bound was removed.

Changed sources: `crates/browser-core/src/observer.rs` and test support/regression
in `crates/browser-core/src/session.rs`. The full workspace rerun passed
**147 tests, one manual benchmark ignored**, including **all twelve stress
cases in 28.58 seconds**. This establishes a concrete deadlock defect and a
passing complete rerun; it does not prove that every historical stall shared
that cause. The optimized PyO3 binding was rebuilt before extension validation.

### Native callbacks are not scoped to the connection that delivered them

`NativeHostController` previously registered the same unguarded callback on
every Native Messaging port. Replaying a queued callback from an old port during
reconnection makes the new handshake fail with the existing negotiation error.
After negotiation, an old snapshot can instead replace the new run and timeline.
Two new deterministic tests fail before the fix and pass afterward. This is an
independent reproduced lifecycle defect, not proof that the user's earlier
screenshot was caused by this exact callback ordering.

The callback now checks its captured port against the current active port before
processing any frame. The existing authentication, negotiated capabilities,
protocol validation, per-run filtering and replay bounds remain intact. Changed
sources: `extension/src/native-host.ts` and `native-host.test.ts`; package and
lock versions advance to **0.2.4**. TypeScript, ESLint, Prettier, all **76**
extension software tests and the production build pass.

### Remaining attached-browser capability failure

The unchanged `multi_tab` differential case still passes Mode A (managed Rust)
and fails Mode B (Rust through the actual extension). The native `_blank` link
opens a Chrome tab, but that tab is absent from the attachment ownership map.
After one action, the fixture reasoner cannot find an owned-tab activation
candidate. Mode C for that case is not reached; no new Mode C pass is claimed.
This reproduction uses fixed decisions and no OpenAI request.

ADR-016 permits explicitly created supporting tabs and excludes arbitrary popup
adoption. Neither enumerating unrelated targets nor silently replacing this run
with managed browsing is an acceptable fix. A bounded, intent-correlated popup
attachment contract remains required before this capability can pass. The
current Browser Use managed-tab implementation is a separate migration path.

## Current completion boundary

The two new fixes do not complete the entire original brief. Popup ownership,
full identifier correlation into Rust, durable extension continuation after a
runtime restart, user-installed Chrome task acceptance and a new real-extension
24-task evaluation remain open. The frozen original tasks/graders are unchanged.
No model tuning, Jev call or new paid inference was used in this follow-up.
