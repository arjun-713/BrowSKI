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
