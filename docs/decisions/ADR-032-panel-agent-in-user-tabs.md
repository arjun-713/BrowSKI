# ADR-032: Side-panel General agent in the user's own tabs

Status: Accepted by the user 2026-10-22; implementation in progress.
Supersedes, for side-panel General tasks only: ADR-022's "managed local Chrome
first" slice, ADR-025's per-interaction approval and quoted-literal text rule,
and the routine "paid inference off" default. Legacy, Fast and CLI rules remain.

## Evidence that forced the change

Reproduced 2026-10-22 through the exact product dispatch (`execute_managed_task`):

- Fast/Laya on `https://en.wikipedia.org/wiki/Main_Page` failed before any
  action: `ValueError: Page exceeds the current 120-candidate Fast limit`,
  reported only as `Fast browser failed (ValueError)`. A cold Laya decision took
  28 s. Laya ranks candidates; it cannot author text, so open-ended tasks
  (search, compose, multi-site) are outside its capability.
- General/OpenAI on "Go to Wikipedia, search for Alan Turing ... date of birth":
  two valid OpenAI responses (3.2 s, 2.2 s), then the policy refused the model's
  `input` because "Alan Turing" was not a quoted task literal. Status `blocked`.
- Product budgets (4 calls, 5 steps, 90 s, `max_failures=1`) end any realistic
  task midway. Without caller URL/H1 checks nothing can be `completed`.
- `.env` credentials load only through `scripts/start-local.sh`.

The OpenAI responses and the Laya model were not at fault.

## User decisions (2026-10-22)

1. Side-panel default: General + OpenAI, paid inference permitted for panel
   tasks. Fast/Laya stays selectable. No silent fallback between them.
2. The agent may type model-authored text and click freely. Approval is required
   only for risky actions: purchase/payment, send/post/publish, delete or other
   destructive changes, account/security changes, and any entry into password or
   payment-card fields.
3. The agent works in the user's own Chrome tabs (with their logins), not an
   isolated profile.
4. Completion without caller checks is decided by an independent judge pass over
   the final state and history, never by the agent's own `done` alone.

## Design

### CDP relay (extension ⇄ Python), no new dependency

Browser Use connects to a browser-level CDP WebSocket. An extension only has
per-tab `chrome.debugger`. The local service therefore hosts a loopback-only
WebSocket (`ws://127.0.0.1:<random port>/devtools/browser/<random token>`), one
client, one lease per task. It emulates the small browser-level surface Browser
Use uses and forwards per-tab commands through Native Messaging:

| Browser-level call | Relay behaviour |
| --- | --- |
| `Target.setDiscoverTargets`, `Target.setAutoAttach` (root) | ack; announce leased tabs (`targetCreated` / `attachedToTarget`) |
| `Target.getTargets`, `Target.getTargetInfo` | leased tabs only |
| `Target.attachToTarget` | new page session ID mapped to the leased tab |
| `Target.createTarget` | new tab in the user's window, attached and leased |
| `Target.closeTarget` | only tabs the agent created; the starting tab is never closed |
| `Target.activateTarget` | activate leased tab |
| `Browser.getVersion` | synthetic |
| `Browser.setDownloadBehavior` | ack, no change |
| `Browser.close`, `Browser.grantPermissions`, `Storage.*` | refused |

Session-level commands are forwarded via `chrome.debugger.sendCommand` to the
tab, or to a flat child session (OOPIF) Chrome reported for that tab. The
extension enforces a separate relay policy (not the Legacy allowlist): cookie,
storage, browser, system, tracing, IO and Fetch domains are refused. Tabs opened
by a leased tab (`openerTabId`) join the lease automatically. Unrelated user tabs
are never visible to the agent. Ending the lease detaches the debugger and leaves
all tabs open. A user-cancelled debugger infobar cancels the task.

The Legacy `debugger.command` allowlist and ADR-016/031 attachments are
unchanged; the relay and a Legacy attachment cannot run at the same time.

### General engine

- Budgets for panel tasks: 60 steps, 150 model calls, 30 minutes, 3 consecutive
  failures; configurable and still bounded.
- Full Browser Use action set except arbitrary JavaScript (`evaluate`) and file
  upload. Navigation is HTTP(S) only.
- Risk classifier runs before click/input/select/send-keys on the fresh target
  (label, role, form context, field type, page). Risky actions use the existing
  approval flow with fresh-state rebinding; denial blocks that action only and
  the agent is told why.
- Completion: caller URL/H1 checks when supplied; otherwise the Browser Use judge
  verdict. `done(success=true)` with a failing or unavailable judge →
  `partially_completed` with the judge's reason.

### Panel contract (additive, Native Messaging protocol v1 unchanged)

- `TimelineEvent`: plain-language `label` (for example `Typed “Alan Turing” into
  Search`), the agent's public step goal in `detail`, optional `pageUrl`.
- `runtime.task.result`: optional `answer` (≤ 4000 chars), `verdict`
  `{verified, reason}`, `stats` `{steps, actions, modelCalls, durationMs}`.

## Consequences

- Panel tasks cost OpenAI usage per task; the cost is visible in result stats.
- Page content and, when needed, screenshots of the user's own tabs go to OpenAI
  under the standard privacy mode; strict modes keep General unavailable.
- Evidence is required before any reliability claim: real short and long tasks
  through the packaged extension, reported with false-success counts.
