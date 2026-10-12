# ADR-018: Local evidence and bounded Luna action batches

- Status: Accepted
- Date: 2026-10-12
- Related: [ADR-008](ADR-008-luna-active-decision-policy.md),
  [ADR-016](ADR-016-extension-owned-tabs.md),
  [ADR-017](ADR-017-explicit-cross-tab-text-transfer.md)

## Context

Live fixture tasks exposed three interface failures: irrelevant action defaults
caused valid clicks to be rejected, valid field mutations did not advance
milestones, and a multi-tab task repeatedly opened the same destination.
Separate Luna requests also account for most measured task latency. The
existing `candidate_actions` field was rejected rather than executed.

## Decision

Keep Luna as the only execution decision provider. Match the meaningful fields
for each action type against runtime candidates, then execute the canonical
runtime action. Fields irrelevant to that action do not create authority.
Targets, values, destinations, expected effects, and meaningful options remain
strictly checked. Models cannot invent selectors or input values.

Local checks expose task-authorized field/selection/checkbox matches and
currently owned requested destinations as booleans. Completion text must be
visible in the viewport. Preserve explicit user stop conditions independently
of the model's plan. Advance ordered milestones only through locally satisfied
evidence; a successful action alone does not prove task progress or completion.

Keep owned tab URLs inside the local runtime for deduplication and destination
proof. Provider context receives only task destination indices or trusted,
user-requested site aliases mapped to owned IDs. Unrelated URLs and tab titles
are excluded. Site mappings are central configuration, not instructions
derived from webpage content.

Permit two exclusive batches of two to four already authorized Luna actions:

- Independent same-page `type`, `select`, or checkbox operations, optionally
  followed by a click as the last action.
- Background `new_tab` actions for distinct user-approved destinations.

Do not mix these families. Navigation, activation, scrolling, arbitrary code,
or newly discovered controls cannot be batched. Before each queued step,
require successful prior verification, no recovery, the same run/page, and
only the locally expected mutation. Tab batches additionally require exactly
one new owned tab with the requested URL and no removals. Rebuild candidates
and authorize the next action again. Unexpected browser changes discard the
remaining queue. Every action retains Rust execution, risk confirmation,
verification, and trace events.

The queue is ephemeral. Clear it on pause, stop, recovery, completion, and
cancellation; never checkpoint queued values or browser snapshots. This
supersedes ADR-017's restriction against executing `candidate_actions` while
preserving its transfer provenance rules.

Run optional Laya comparisons in one owned, bounded background task. Busy
comparisons may be skipped. Timeout disables further comparisons for that run;
shutdown cancels the owned task. Laya remains uncalibrated shadow telemetry and
cannot approve actions, completion, or recovery.

## Alternatives and tradeoffs

One model call per action is simpler but repeats model latency for independent
operations. Unchecked sequences would save calls but could act on stale state.
The selected approach permits a small queue and pays deterministic observation
and verification for every action. Conservative comparison may discard a safe
batch on harmless layout changes; the runtime asks Luna again instead.

An identical model echo of the already installed milestone plan can be removed
at the adapter boundary. New or changed plan data on an action response remains
invalid. This normalization does not authorize an action or a replacement plan.
Suggested actions accompanying a milestone plan are discarded rather than
queued. The next action decision still requires a fresh finite candidate set.
Conjunction evidence accepts `;` or ` AND ` only when each term is a recognized
local check; arbitrary expressions are never evaluated.

## Compatibility and evidence

No browser schema, binding API, extension protocol, or package ID changes.
The reasoning interface gains optional Python-only check/label fields; existing
providers remain compatible. Strict finite-action authorization applies to
planning, replanning, and queued actions alike.

The [live repair report](../development/live-agent-repair-2026-10-12.md)
records successful and failed attempts, measured latencies, and local fixture
limits. These results do not establish universal website reliability or Laya
execution readiness. Full model benchmarking and tuning remain separate work.
