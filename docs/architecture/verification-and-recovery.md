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

## Low-level vs high-level recovery

Mechanical problems (the page moved under us) are fixed mechanically without
spending model calls. Strategic problems (the plan is wrong, the site blocks
us, we are stagnating) go to the agent, which can see the whole task. Mixing
the two — e.g. prompting the model to fix a stale node — wastes money and
hides bugs. Recovery is a subsystem with typed decisions on both levels, not
a prompt instruction.
