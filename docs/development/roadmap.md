# Roadmap

Every phase has a measurable gate. Do not start the next phase’s headline
work until the gate is met (docs and small refactors may proceed in parallel).

## M0. Scaffold + research (DONE)

Build the repo, contracts, docs, and minimal executable slice.
Gate: the Definition of Done in `AGENTS.md` §14 — `make test` and `make
lint` green, Chromium launch/navigate/observe/close proven from Python.

## M1. Persistent browser runtime (DONE)

Persistent multiplexed CDP session, tab/frame coordination, browser event
stream, graceful lifecycle (crash/disconnect handling). Design:
`docs/architecture/browser-runtime.md`.

| Test                            |                                 Gate | M1 result |
| ------------------------------- | -----------------------------------: | --------- |
| Sequential navigation           |                              100/100 | 100/100 (p50 30ms, p95 40ms, p99 58ms) |
| Cross-tab create/navigate/close |                           100 cycles | 100/100 (p50 87ms, p95 103ms, p99 186ms) |
| Rapid tab creation              |                             25+ tabs | 25 tracked + closed |
| Repeated frame attach/detach    |                zero state corruption | 50/50 events, registry settles to main frame |
| Browser shutdown                |     zero orphaned Chromium processes | pgrep-clean after close |
| Failed navigation               |               runtime remains usable | usable; error pages fast-fail |
| Tab closed externally           |                   detected correctly | TargetDestroyed detected + registry pruned |
| Browser killed externally       |       deterministic disconnect event | ConnectionLost; terminal errors, no stranded requests |
| CDP command timeout             |        no deadlocked pending request | timeout + reuse clean, pending 0 |
| Concurrent CDP commands         | response correlation remains correct | 50/50 exact (p50 8.7ms, p95 11.9ms) |

Also measured: RSS +10→10 fds, +12.7→13.0MB RSS across 3 launch/close
cycles. Suite: `cargo test -p browser-agent-core --test stress_runtime`
(~55s, local fixture server, serialized).

## M2. Observation + element identity (DONE)

Full DOM/AX/layout collection, `SemanticSnapshot` population, stable refs
with reacquisition across small page changes. Design:
`docs/architecture/observation-model.md`, ADR-003. No OCR/VLM by decision.

| Area | Gate | M2 result |
|---|---|---|
| Basic controls | ≥99% discovered | 9/9 named + radios/values/forms |
| Accessible custom controls | ≥98% | role=button/combobox/checkbox from divs |
| Stable refs after benign DOM mutation | ≥98% | 16/16, same ids + fingerprints |
| Refs after reorder | ≥98% | 5/5 |
| Refs after inserted sibling | ≥98% | all kept + exact 1-added delta |
| Duplicate-label disambiguation | 100% deterministic | `@continue/_2`, `@billing/_shipping_continue`, stable ids |
| iframe provenance | 100% | `main → iframe[..]`, 3-level nesting |
| open shadow DOM | supported | pierced, `>>shadow` ancestry; closed absent |
| hidden elements incorrectly exposed | <1% | 0 interactable of 6 hidden classes |
| interactability classification | ≥98% fixture accuracy | occluded/disabled/readonly/inert/offscreen/dialog all correct |
| state diff correctness | 100% deterministic fixtures | value delta `"" → "bob"`, add/remove/move/nav deltas |
| stale reference detection | 100% | generation comparison + unknown → None |
| ambiguous reacquisition | must not silently bind | unit + integration refused |
| observation determinism | identical page → identical output | fingerprints + ids + aliases equal |

Also measured: full observation 190–665ms on fixtures (local pages).
Suite: `cargo test -p browser-agent-core --test observation_m2` (15 tests,
local fixture corpus `tests/fixtures/m2/`, 16 pages). Python surface
(`tabs/render_observation/observe_delta/resolve`) covered by
`python/tests/test_session_smoke.py::test_m2_render_delta_and_resolve`.

## M3. Executor + deterministic verification (DONE)

Typed browser actions execute through trusted browser input, bounded settling,
and deterministic postcondition verification. Outcomes include structured
failures and evidence. Coverage includes forms, navigation/history, tabs,
dialogs, hover, scrolling, native selects, and stale/ambiguous targets.

Validation on 2026-10-06: the M3 integration suite passed 24 tests, including
verified textarea typing and refusal after a target disappears. The suite now
fails immediately if Chrome or Chromium is unavailable, so a missing browser
cannot look like a passing browser gate. Full workspace quality-gate status is
reported with the current M3–M7 validation run. This gate does not claim Python
agent integration.

The opt-in local action-latency harness now reports external observation,
pre-action observation, target resolution, action execution, mechanical
recovery, settling, post-action observation, delta, verification, and total
latency separately. The first 40-sample result is recorded in
[`benchmarks/reports/action-latency-2026-10-06.md`](../../benchmarks/reports/action-latency-2026-10-06.md).

## M4. LangGraph agent runtime (DONE)

Implemented typed `AgentState`, observe/decide/execute/verify nodes, bounded
step and decision counts, and a LangGraph checkpointer. PyO3 exposes the Rust
typed action/outcome API as JSON; Python validates action contracts before
crossing that boundary. A deterministic fake agent navigates a local form,
checks a control, and stops only after inspecting the verified result.
`AgentRuntime.open_sqlite` scopes an async SQLite checkpointer to a runtime
context. Tests verify runtime resume after reopening the database and recovery
from a separate process. Checkpoints store bounded task state and a compact
snapshot summary; full semantic snapshots remain in the live runtime cache.
In-memory saver injection remains available for lightweight tests. No Laya,
Jev, or Luna model is used by M4.

Validation on 2026-10-02: 13 Python tests passed before durable checkpointing;
the SQLite cross-process and runtime-reconstruction checks are part of the
current full Python suite. Ruff format/check and strict Pyright passed. The
Rust/Python extension build included the new action binding.

The installed `browski run "task"` command runs the graph with an optional
starting URL, provider selection, and SQLite checkpoint database. `browski
task` remains an equivalent spelling, and `agent` remains a compatibility
entry point. The `resume` command reopens the saved graph thread and supports
explicit approval or denial of a pending high-risk action. A process restart
starts a fresh browser session and re-observes before acting; restoring or
attaching to the previous Chromium process and page-local state is not
supported by the current binding.

## M5. System One decisions (DONE)

Added a shared `DecisionProvider`, local CPU `LayaProvider` default, optional
`JevProvider`, and Laya-first adaptive fallback. Both adapters support bounded
Choice, Score, and Noul decisions, semantic verification, recovery classification,
and progress checks. Calibration policies and thresholds are provider-specific;
default thresholds remain unset pending held-out BROWSKI task data. Tests use
fake model and SDK clients, so they prove adapter contracts but do not measure
live model quality, calibration, CPU latency, or Jev API behavior.

The Laya adapter calls an explicitly managed local service on CPU by default;
it does not download weights in the browser-agent process. The finite candidate
builder offers only bounded semantic actions or planner escalation, then binds
the selected candidate through Rust-owned semantic references. Provider health,
timeouts, typed errors, and fallback telemetry are explicit.

Gate passed: fake-backed provider contracts, candidate bounds and binding,
health and timeout handling, provider-specific acceptance, and observable
adaptive routing. Optional live checks remain opt-in; live quality and
benchmark validation are not established by contract tests.

## M6. GPT-6 Luna + adaptive reasoning (DONE; live API unverified)

Added the only generative reasoning provider in the baseline and a
deterministic `ComplexityGate`. The OpenAI adapter uses the Responses API with
structured output, default model `gpt-6-luna`, a context/output bound, and a
request deadline. Install it with the `reasoning-openai` optional dependency;
the SDK and API key are required only when Luna is called. The model identifier
and supported reasoning-effort choices were checked against the
[OpenAI model catalog](https://developers.openai.com/api/docs/models) and
[structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

`LunaDecisionAgent` tries the configured `DecisionProvider` first. It sends
only bounded semantic candidates to Laya/Jev, escalates abstentions and
unsupported planning to structured Luna decisions, and binds model actions to
current interactable semantic refs. A short milestone plan carries visible
evidence phrases that the graph checks against later browser observations.
`BROWSKI_LUNA_MODEL` can override the model identifier; the default remains
`gpt-6-luna`. Normal reasoning uses low effort; high effort is selected only
when the recovery ladder's deterministic gate promotes a failed normal replan
or other complex state. There is no xhigh route. Progress after a complex
decision resets the per-streak escalation counters.

Fake-backed adapter and agent tests do not establish live API availability,
model quality, or task success. Focused checks passed for model configuration,
per-call effort reset, adapter contracts, and deterministic escalation. The
live OpenAI test is opt-in and requires `BROWSKI_LIVE_OPENAI=1` plus an API key;
no live request was made for this validation run.

## M7. Memory, progress, and recovery (CORE IMPLEMENTED)

The Python runtime now carries bounded structured working memory, task goals,
constraints, milestones, visible evidence, capped action/recovery histories,
and checkpoint summaries. Progress uses semantic controls, document changes,
visible text, verification, and milestone signals; repeated actions and states
are bounded by stagnation and recovery budgets. Completion claims require a
verified action plus configured task evidence and required milestones.

High-risk actions suspend the graph for explicit approval. Confirmation and
action-history summaries omit typed values and URL data. Local tests cover an
11-step long-horizon task, recovery bounds, completion refusal, and
approval/denial.

The recovery policy routes through System One, one normal Luna replan, the
ComplexityGate, and at most one high-reasoning replan. Unavailable reasoning
does not run and recovery asks the user or stops within its configured bounds.

Provider telemetry records bounded provider/model labels, operation and
outcome, fallback routing, and provider-reported token counts when available;
it does not estimate cost. Luna and Laya/Jev decision events include run and
step IDs. No live provider response was used to verify token-usage reporting.

### Local graph/checkpoint microbenchmark (2026-10-05)

Using the BROWSKI graph's observe/decide/completion-check path with a fake
browser observation and fake agent, 40 measured invocations per case after
five warmups produced these medians (p95): no saver 1.792 ms (2.112 ms),
in-memory saver 2.264 ms (2.810 ms), and SQLite saver 4.773 ms (5.625 ms).
Checkpoint state reads measured 0.148 ms (0.235 ms) in memory and 0.552 ms
(0.638 ms) with SQLite. Environment: Python 3.12.13, LangGraph 1.2.12,
langgraph-checkpoint-sqlite 3.1.1, Fedora 44 x86_64. These local microbenchmarks
exclude CDP, actions, verification, providers, and recovery; they are not
end-to-end browser-task latency measurements.

The graph/checkpoint microbenchmark above measures orchestration and saver
overhead with fake agents and observations. The separate local browser study
now measures a small deterministic action path; see the report linked in M3.
Its 404 ms median settle phase dominates the 427 ms total median on a
single-checkbox data page. Historical M1 and M2 figures use different
operations and fixtures, so they are context only and do not establish a
before/after comparison. Live provider latency and end-to-end task latency
remain unmeasured.

## M8. Vision fallback (future)

On-demand multimodal interpretation for semantic dead ends; not the primary
page representation.

## M9. Browser-code escape hatch (future)

An explicitly enabled, restricted, traced, and time-bounded tool for difficult
deterministic browser operations.

## M10. Privacy mode (future)

Optional PII/secret detection, tokenization, sanitized screenshots, and local
visual processing. These are not mandatory middleware for every action.

## M11. Product surface (future)

CLI, SDK, trace viewer, optional extension, packaging, examples, and user docs.

## M12. Benchmark hardening (future)

Run representative long-horizon evaluations and publish reproducible results.
No comparative claim without controlled benchmark evidence.
