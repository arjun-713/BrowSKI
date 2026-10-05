# Verification and recovery

## Action verification

Every browser action carries an `expected_effect` (all actions except raw
`Wait`). After execution, `verification` compares expected vs observed using
before/after snapshots and returns:

- `SUCCESS` — postcondition holds (e.g. URL became X, field value became Y).
- `FAILURE` — postcondition does not hold, with evidence and state delta.
- `UNCERTAIN` — cannot be determined from available state; escalate, do not
  assume success.

A tool call completing without exception is transport success, not action
success. Unverified actions never update task progress.

## State transitions

Each session carries a monotonic `generation`, bumped on navigation. Actions
record `before_generation`/`after_generation`; progress and memory key off
generations so stale observations cannot silently drive decisions.

## Failure taxonomy

Initial categories (owners in `../development/failure-taxonomy.md`):
`GROUNDING, PLANNING, MEMORY, EXECUTION, VERIFICATION, RECOVERY, VISION,
NAVIGATION, FRAME, TAB, UPLOAD, DOWNLOAD, AUTH, TIMEOUT, STAGNATION,
SITE_BLOCK, MODEL_FORMAT, SAFETY, UNKNOWN`.

## Bounded retry

- Low-level (Rust, `crates/recovery`): stale nodes → reacquire + retry;
  detached frames, intercepted actions, navigation races → classified retry.
  Cap: `MAX_MECHANICAL_RETRIES = 3`, then escalate with evidence.
- High-level (Python, `recovery/`): replan, alternate strategy, escalate to
  the user. Also bounded (`RecoveryPolicy.max_replans`).

The Python recovery budget names the bounded ladder: one mechanical repair,
reobserve, bounded alternate action, System One classification, one normal Luna
replan, ComplexityGate, at most one high Luna replan, ask the user, then
terminate. Only available capabilities may run. The ComplexityGate runs after
a failed normal replan and records its level and reasons in recovery history.
High effort is temporary; successful progress clears the escalation streak.

Progress records distinguish activity from meaningful change. The bounded
stagnation detector tracks repeated state/action pairs, A–B cycles, uncertain
verification, and recovery without progress. Its rolling sample window and
per-run recovery/action budgets prevent unbounded retry loops.

## Completion and consequential actions

A model completion claim is accepted only after deterministic successful
verification and satisfaction of required milestones and configured visible
evidence. Semantic completion probability may add a future bounded check; it
cannot replace deterministic evidence.

High-risk actions, including form submission, Enter in a form, and controls
labelled for consequential operations, suspend the graph. The caller must
resume with an explicit approval or denial. Action-history and approval
summaries contain action type and semantic target reference, not typed values
or URL data.

## Low-level vs high-level recovery

Mechanical problems (the page moved under us) are fixed mechanically without
spending model calls. Strategic problems (the plan is wrong, the site blocks
us, we are stagnating) go to the agent, which can see the whole task. Mixing
the two — e.g. prompting the model to fix a stale node — wastes money and
hides bugs. Recovery is a subsystem with typed decisions on both levels, not
a prompt instruction.
