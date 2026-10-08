# Live headless agent smoke diagnosis — 2026-10-09

## Scope and environment

Four small tasks used real headless Chromium and the existing BROWSKI runtime
at commit `ff5da36`. Requests went through the configured provider boundary to
`gpt-6-luna`, with `low` reasoning effort. Credentials stayed in the local
backend. No Jev requests, Laya tuning, or agent implementation changes were
made. Laya remained non-executing shadow telemetry.

Three tasks used managed browsers. The fourth loaded the actual packaged
extension, version `0.1.1`, into an isolated Chromium profile, registered its
Native Messaging host inside that profile, connected through the side panel,
and attached to a local fixture tab. It used the shared Rust browser engine
and real Luna responses, not a fixture decision provider.

Environment: Fedora Linux, kernel `7.2.7-200.fc44.x86_64`, Python `3.12.13`.
The tasks used deterministic local fixtures; the user's signed-in Google Forms
tab was not modified. These four attempts diagnose failures and do not
estimate general task-success rates.

## Results

| Task                                    | Mode               | Actions executed | Luna calls |      Time | Independent goal check                        |
| --------------------------------------- | ------------------ | ---------------: | ---------: | --------: | --------------------------------------------- |
| Click Increment exactly once            | Managed            |                0 |          1 |   9.829 s | Failed; counter remained 0                    |
| Select Karnataka in State dropdown      | Managed            |                0 |          1 |   4.554 s | Failed; Choose remained selected              |
| Scroll until bottom text is in viewport | Managed            |                0 |          2 |  14.922 s | Failed; text remained below viewport          |
| Fill name and continue to role details  | Extension attached |                9 |         11 | 103.906 s | Partial; name filled, next section not opened |

The three managed runs ended `awaiting_user`. The attached graph also ended
`awaiting_user`; the extension mapped that result to its displayed `failed`
status. There were **zero complete goals out of four attempts**.

All 15 Luna calls returned completed structured responses: 34,369 input tokens
and 2,786 output tokens. Logged API-response latency had a median of 3.420 s,
a minimum of 2.241 s, and a maximum of 9.911 s. These are API-call latencies,
not total task latencies. No paid request was retried after changing a prompt
or runtime policy.

## Confirmed failure points

### 1. Irrelevant action fields cause false candidate rejection

The click proposal used the correct type and target, `click @increment`. The
scroll proposal matched the candidate's `dx=0, dy=600`. Both were rejected
because Luna returned `clear=false`, while the candidate's `BrowserAction`
had default `clear=true`. The debug comparison identified only `clear` as
different for the intended candidate.

Evidence:

- [Click response and rejection](../../debug-logs/smoke-managed-click-70993427/events.jsonl), records 6–7.
- [Scroll response and rejection](../../debug-logs/smoke-managed-scroll-aed20475/events.jsonl), records 10–11.
- [Attached Continue click and rejection](../../debug-logs/4b872a4a-9b4b-4d99-b319-e5604ae76ca5/events.jsonl), records 146–147.
- [`_action_signature`](../../python/src/browser_agent/agent/luna.py) includes
  all non-null action fields, including defaults irrelevant to these actions.

This is a BROWSKI action-contract matching problem. The model selected the
intended semantic action in these three rejections. The candidate guard
refused execution as configured; removing the guard would not be a sound fix.

Recommended repair: normalize or compare fields according to action type.
Keep targets, generations, text, submission flags where meaningful, and scroll
deltas strictly authorized. Another approach is selecting a candidate ID and
materializing the already authorized runtime action. Add regressions for
irrelevant-field differences and genuinely unauthorized differences.

### 2. Explicit dropdown intent never becomes a selectable candidate

The observation contained the State combobox and Karnataka option. The model
received only scroll and escalation candidates, so it correctly asked for a
selection action instead of inventing one.

Evidence: [Select request and response](../../debug-logs/smoke-managed-select-81cb02cb/events.jsonl),
records 5–6. [`CandidatePolicy`](../../python/src/browser_agent/decisions/candidates.py)
has an empty default `select_values_by_ref`. The
[task-value parser](../../python/src/browser_agent/decisions/task_values.py)
binds quoted set/fill/type instructions to text fields; it does not derive
this plain-language select instruction into an authorized combobox choice.

Recommended repair: construct a bounded selection from explicit user intent
and a uniquely matching observed combobox/option. Preserve label/value
semantics and refuse ambiguity. Do not authorize invented selections.

### 3. Successful typing does not advance the subgoal

The attached browser really acquired `Full name = Smoke Tester`, as checked
directly with Playwright after the task. The next section remained hidden.
The first typing action changed state; subsequent requests repeatedly chose
the same typing action. Nine typing actions were executed and verified.

The planner's observation omitted the field value both before and after
typing. [`_agent_observation`](../../python/src/browser_agent/agent/luna.py)
explicitly sets `value=None`. The plan's first completion evidence was the
phrase `Full name field contains Smoke Tester`. The
[graph](../../python/src/browser_agent/agent/graph.py) checks evidence using
substring matching against `_visible_text`, which includes page prose and
accessible names, but not form values. That sentence never appears as page
text. Consequently, completed milestones stayed empty and the current
subgoal remained the name-entry step.

Evidence: [Attached log](../../debug-logs/4b872a4a-9b4b-4d99-b319-e5604ae76ca5/events.jsonl),
records 7, 10–12, 19, 25–27, and later repetitions through record 145.

Recommended repair: verify explicit user-authorized field assignments locally
and publish a structured completion fact. Advance the matching subgoal from
that evidence. Avoid exposing arbitrary private field values merely to make
the planner aware of completed work.

### 4. Verification success masks repeated no-op actions

The [progress tracker](../../python/src/browser_agent/progress/task_state.py)
adds `VERIFICATION_SUCCESS` whenever an action verifies and treats any signal
as progress. The graph therefore resets stagnation even when the task does
not advance. Later requests showed `stagnant_steps=0` and only verification
success as the progress signal while repeating the same typing action.

Recommended repair: distinguish a satisfied action postcondition from new
task progress. Already-satisfied actions need no-op detection and repeated
state/action detection. Preserve deterministic verification; do not weaken
it to force a milestone to complete.

The run eventually stopped when Luna proposed the Continue click, which then
hit the `clear` mismatch. It did not stop because stagnation caught the loop.

### 5. Shadow inference adds latency to the active path

The attached run performed nine Laya shadow requests: eight timed out near
5 s and one returned after 4.855 s. Shadow comparison was awaited before
the active action, adding approximately 44.9 s of waiting across this run.
The successful response yielded no parsed semantic choice for comparison.

Evidence: [Attached log](../../debug-logs/4b872a4a-9b4b-4d99-b319-e5604ae76ca5/events.jsonl),
records 13–14, 28–29, 43–44, and subsequent shadow pairs. No shadow output
authorized an action or changed Luna's choice.

Recommended repair: isolate optional shadow collection from active-path
latency, with bounded scheduling and lifecycle ownership, or disable shadow
for interactive diagnosis. This is a latency finding, not a calibration result.

## Evidence and reproduction

Local artifacts are ignored by Git and stored under
[`debug-logs/live-smoke-20261008T184458Z/`](../../debug-logs/live-smoke-20261008T184458Z/):

- `cases.json`: prompts fixed before the first request.
- `results.json`: run IDs, statuses, independent checks, and side-panel trace.
- `summary.json` and `provider-calls.csv`: API usage and latency summaries.
- `managed-*-before.json` / `managed-*-after.json`: synthetic browser snapshots.
- `attached-form-after.json`: final attached-browser snapshot.
- `runner.py` and `attached_only.py`: diagnostic harness, retained locally.

Frozen case SHA-256:
`53739a33eb3adb3b40178ddb706a2b0d517d127f7ebe2a512020f66a0a017459`.
Raw session JSONL paths are linked above. Capture contains sanitized public
provider responses, not hidden reasoning or credentials. Sanitization can
omit fields; the separate synthetic snapshots and final DOM checks supplement
the debug records.

An initial attached-test setup failed because its Unix socket path exceeded
the backend's 100-byte limit. The harness was corrected to use a short `/tmp`
socket and only the attached case was started again. That initial attempt
made no attached-task API request. Production service, extension source, and
user browser profile were unchanged. All isolated browsers and the temporary
service were closed after the smoke run.

## Repair order

1. Fix action-type-aware candidate matching, with strict authorization tests.
2. Add structured local evidence for authorized input/subgoal completion.
3. Make repeated verified no-ops count toward stagnation.
4. Add explicit bounded dropdown candidate construction.
5. Remove shadow inference waiting from the interactive action path.

Then rerun the same tasks before trying the signed-in Google Forms workflow.
Browser observation, extension attachment, and verified typing worked here;
the failures were exposed in candidate matching, candidate coverage, and
state/progress representation. This run does not establish that all browser
mechanics or the Google Forms workflow are correct.

## Validation

No runtime implementation or extension change was made in this diagnosis.

- Temporary harness: Ruff format and lint passed.
- `make lint`: Rust format, Clippy with warnings denied, Ruff format/lint,
  and Pyright passed; Pyright reported zero errors.
- `make test`: Rust reported 129 passed and one intentionally ignored manual
  latency test. Python reported 359 passed and 16 skipped.
- Opt-in packaged extension E2E suite: 13 tests passed with real headless
  Chromium. Its provider fixtures test software contracts; the four live
  tasks above separately establish the observed model-backed outcomes.
- Changed-document local links: 30 targets checked, none missing.
- Prettier checks and `git diff --check` passed.
- Configured-key leakage check: zero occurrences in 19 smoke evidence files.
  This checks the actual configured key; it is not a universal privacy audit.
- Existing backend supervisor remained running and Laya health returned 200
  after the isolated browsers and temporary service were closed.

Gate console outputs are retained with the ignored local smoke artifacts.
Passing software tests did not prevent these live task failures. Add
regressions for the confirmed failure paths before treating a repair as done.
