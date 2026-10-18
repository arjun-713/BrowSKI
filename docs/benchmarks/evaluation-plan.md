# Evaluation plan

## North-star metric

**TASK SUCCESS RATE** — fraction of tasks completed end-to-end, judged
against explicit completion criteria per task. This is the primary metric
(principle 1); everything below explains _why_ it moved.

## Tracked alongside

- partial completion (milestone credit)
- number of steps
- number of LLM calls
- token usage (input/output)
- cost (USD)
- wall-clock latency
- action failure rate
- verification failure rate
- recovery success rate
- stagnation rate

## Integration targets (future, not yet integrated)

| Suite                        | Covers                                                 |
| ---------------------------- | ------------------------------------------------------ |
| BrowserGym                   | Gym-style web-task harness, multi-benchmark runner     |
| AgentLab                     | Large-scale reproducible evaluation workflows          |
| WebArena / WebArena-Verified | Self-hosted realistic web tasks                        |
| VisualWebArena               | Vision-heavy tasks                                     |
| WorkArena                    | Enterprise-workflow tasks                              |
| AssistantBench               | Long-horizon assistant tasks                           |
| BU Bench                     | Browser-Use community benchmark                        |
| Mind2Web-family              | Grounding/action-prediction evaluation where practical |

Phase the integrations: `benchmarks/synthetic/` first (deterministic local
pages we control), then BrowserGym as the primary external harness
(Milestone 9). Do not integrate everything at once; each integration must
report the full metric set above into `benchmarks/reports/`.

## Rules

- Benchmarks exist from the beginning; the scaffolding (`benchmarks/`,
  reports dir, metric definitions) is the Milestone 0 deliverable.
- Do not claim an improvement — or parity/superiority with any system —
  without measured numbers on a named suite.

## BROWSKI 2.0 controlled navigation first look — 2026-10-18

Frozen [four-case manifest](../../benchmarks/synthetic/v2-navigation-first-look.json),
SHA-256 `c2cb313ea04549a3562bc719d1f52645babde46b2a028f52551d7ffea3480da1`.
Runtime baseline `0ebefdb`, before the destination-grounding changes in ADR-024.
These cases were not used to tune the implementation before this run. They are
now spent evaluation cases; subsequent runs are regressions, not fresh holdouts.

Each task ran through the packaged extension, authenticated Native Messaging,
product dispatch, CPU Laya v19s, official Browser Use browser mechanics and fresh
caller-owned final URL/visible-H1 checks. Expected criteria were not supplied to
the decision questions. The fixture graph and minimum-action assertion also
check the required two- or three-click path. No generative/hosted inference was used.

| Case                        | Verified | Decisions | Actions | Reacquisitions | Engine elapsed |
| --------------------------- | -------- | --------: | ------: | -------------: | -------------: |
| Museum accessibility guide  | yes      |         3 |       2 |              1 |        15.75 s |
| Cedar Ridge weather advice  | yes      |         4 |       3 |              1 |        15.95 s |
| Online refund deadline page | yes      |         3 |       2 |              1 |        17.11 s |
| Beginner pottery class page | yes      |         3 |       2 |              1 |        16.19 s |

Observed task success: **4/4**. False successes against these criteria: **0/4**.
13 local decisions, 9 browser actions, 4 freshness reacquisitions, 0 recorded
provider errors, 0 generative calls. Mean engine elapsed 16.25 s; median reported
model inference 809 ms over 13 decisions. Engine elapsed includes cold startup
and cleanup. The test harness took 132.41 s overall. Memory was not newly measured
in this run; use the separately scoped phase-4 CPU measurement. Reacquisition
counts do not establish recovery from a labelled website failure.

This is a small, controlled navigation sample, not a public-web success estimate
or evidence for forms, dates, dropdowns, tabs, authentication or long workflows.
The upstream tokenizer warning remains. Do not infer production readiness from it.

Reproduce as a regression (prepared checkpoint and built extension required):

```sh
PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" \
BROWSKI_EXTENSION_E2E=1 BROWSKI_V2_HOLDOUT_E2E=1 \
python/.venv/bin/pytest -s python/tests/extension/test_managed_e2e.py -k first_look
```

The href-only real-Chrome regression is a separate mechanical test. After a stable
observation, changing an anchor's destination without its label/backend ID caused
one wrong click in the old code. The destination-aware fingerprint refuses that
click and reacquires the page. This is mechanical correctness evidence, not an
increase in autonomous task success on the four-case sample.

## Managed General form compatibility gate

The phase-7 form slice uses `test_managed_general_form_approval_from_packaged_panel`
in the existing managed E2E module. It runs the actual packaged sidebar, Native
Messaging service, official Browser Use Agent and local Chrome. HTTP inference
is explicitly replaced with deterministic responses; there are **zero paid
provider requests**. This is an integration/regression gate, not an autonomous
General success-rate benchmark.

The task enters the quoted literal `Ada` in a local draft and saves it. The
fixture changes to `/receipt.html?name=Ada` with the visible H1 `Saved demo record`
only if the actual input value matches. The test checks the empty field before
approval, the actual value after approved typing, and no receipt before approving
the button. It then varies the button response:

| Variant                     | Required terminal outcome | Required effect                                       |
| --------------------------- | ------------------------- | ----------------------------------------------------- |
| Approve                     | completed, verified       | Exact receipt URL/H1; three executed actions          |
| Deny                        | blocked, unverified       | No save; only navigation and approved typing          |
| Stop                        | cancelled, unverified     | No pending click; card cleared and browser cleaned up |
| Field changed during review | blocked, unverified       | No save after stale approval                          |

Separate real-Chrome tool cases cover approved/denied text entry, a live field
property mutation, append input, invented text and password fields. Task-control
checks cover one-use approval IDs, expiry, Stop and a pre-existing Pause. These
prove bounded execution/approval behavior. They do not measure dates, selects,
authentication, source-to-field synthesis, public-site forms or live generative
model decision quality. The current caller-owned URL/H1 verifier is not a generic
business-workflow verifier. Keep broader outcome checks and unseen task
acceptance open, and retain Legacy capabilities until replacements pass.

The 2026-10-18 packaged run passed all four approval variants. The full packaged
suite passed 21 tests with the two CPU-Laya opt-ins enabled and four spent
navigation opt-ins skipped. No live General form inference was measured.

## Fast quoted text-field development gate

ADR-026 adds ordinary text fields without a generative model. The development
case sets Name to Ada and City to Pune on a page whose URL/H1 already matches
its caller-owned check. Completion must wait for both actual values, not just
that initial page match. The first live CPU-Laya engine run completed two input
actions in 24.66 s with two decisions (1717/1811 ms), no provider errors,
recoveries or generative calls. These are one-task development timings, not a
latency benchmark, memory measurement or unseen success-rate estimate.

The same task also passed through the packaged default-Fast sidebar, without
Legacy attachment or hosted credential access, with two distinct user approvals.
Native reads confirm both field values. Real-Chrome regressions cover a value
changed before execution (zero typing actions), a page masking Ada to ADA
(unverified with one invoked action), and missing/duplicate labels (partial,
never completed). Input control characters are rejected before approval. Strict
intent tests reject conflicts, incomplete/unquoted/blank/overlong assignments
and more than eight bindings; instruction-like literal contents remain data.

Both Laya and Jev pass offline adapter cases for the exact same TYPE_TEXT
question/candidate state. Live Jev is still unverified. This gate does not cover
submit buttons, native dates, dropdowns, uploads, source transfer or retained
browser sessions; task browsers still close at completion. It is a development
vertical slice and mechanical regression coverage, not a new autonomous holdout.

## Fast native-control development gate

ADR-027 adds native dates and single-select dropdowns to the same quoted-value
workflow. The development task sets Departure to 2026-11-03 and Color to Blue.
Independent reads require exact date value and native validity, plus the actual
selected option's label/value. Real CPU Laya completed two actions/decisions in
15.77 s, with 1582/1050 ms decision times, no generative calls, provider errors
or recoveries. These timings overlap development validation and are not a speed
comparison. The actual packaged default-Fast sidebar also passed, requiring two
approvals and no Legacy attachment or hosted credential lookup.

The existing parameterized workflow suite covers fixture and actual CPU Laya,
impossible/ranged dates, token collisions, duplicate option labels/values, HTML
option label attributes, disabled options, multiple selects, stale constraints,
delayed options with/without recovery, replaced controls and wrong replacement
values. A replacement-date regression improved from blocked after one write to
completed with two actions and one read recovery, without repeating the write.
A separate regression reproduced false completion after a later action removed
a verified date; rebuilding proof each observation now returns partially_completed.
Negative cases must remain unverified; success cannot come from SDK return status
or cached field proof. Both adapters pass equivalent SELECT contract fixtures;
live Jev remains unverified.

These are controlled development cases, not an unseen success-rate estimate.
Keep custom controls, submit workflows, source transfer, tabs/auth and retained
sessions outside this gate. Use a fresh frozen end-to-end task set after further
workflow work; the four navigation first-look cases are already spent.
