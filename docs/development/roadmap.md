# Roadmap

Every phase has a measurable gate. Do not start the next phase’s headline
work until the gate is met (docs and small refactors may proceed in parallel).

## M0. Scaffold + research (DONE)

Build the repo, contracts, docs, and minimal executable slice.
Gate: the repository rules in `AGENTS.md` — `make test` and `make
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

## M5. System One decisions (CONTRACTS DONE; LAYA SHADOW ONLY)

Added a shared `DecisionProvider`, local CPU `LayaProvider`, optional
`JevProvider`, and provider-specific calibration interfaces. Both adapters
support bounded Choice, Score, and Noul decisions, semantic verification,
recovery classification, and progress checks. Current product policy makes
GPT-6 Luna the only executable decision path, keeps Laya shadow-only, and
disables Jev. The Laya benchmark found it untrusted for execution. No Laya
tuning or Jev calls are part of this productization phase.

The Laya adapter calls an explicitly managed local service on CPU by default;
it does not download weights in the browser-agent process. The finite candidate
builder offers bounded semantic actions and escalation, and Rust-owned semantic
references are required for executable actions. Provider health, timeouts,
typed errors, and fallback telemetry are explicit.

Gate passed: fake-backed provider contracts, candidate bounds and binding,
health and timeout handling, provider-specific acceptance, and observable
adaptive routing. Optional live checks remain opt-in; live quality and
benchmark validation are not established by contract tests.

## M6. GPT-6 Luna + adaptive reasoning (IMPLEMENTED; limited live evidence)

Added the only generative reasoning provider in the baseline and a
deterministic `ComplexityGate`. The OpenAI adapter uses the Responses API with
structured output, default model `gpt-6-luna`, a context/output bound, and a
request deadline. Install it with the `reasoning-openai` optional dependency;
the SDK and API key are required only when Luna is called. The model identifier
and supported reasoning-effort choices were checked against the
[OpenAI model catalog](https://developers.openai.com/api/docs/models) and
[structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

`LunaDecisionAgent` is the current executable decision path. It sends bounded
semantic candidates to Luna, requires Luna's action to match one of those
candidates, then may ask Laya for a shadow comparison that cannot change the
action. Unsupported outputs fail closed. A short milestone plan carries
visible evidence phrases that the graph checks against later browser
observations.
`BROWSKI_LUNA_MODEL` can override the model identifier; the default remains
`gpt-6-luna`. Normal reasoning uses low effort; high effort is selected only
when the recovery ladder's deterministic gate promotes a failed normal replan
or other complex state. There is no xhigh route. Progress after a complex
decision resets the per-streak escalation counters.

Fake-backed adapter and agent tests do not establish live API availability,
model quality, or task success. Focused checks passed for model configuration,
per-call effort reset, adapter contracts, and deterministic escalation. The
live OpenAI test is opt-in and requires `BROWSKI_LIVE_OPENAI=1` plus an API key;
no live request was made for the original milestone validation run.
Subsequent [live repair](live-agent-repair-2026-10-12.md) and
[frozen mixed-task](task-mix-evaluation-2026-10-14.md) evaluations record real
API outcomes. The latter passed 11/18 development tasks and 4/9 held-out tasks;
long-task reliability remains unestablished. The adapter now records explicit
prompt-cache reads and writes; see [the cache boundary](../architecture/prompt-caching.md).
The final frozen V8 rerun later passed 16/18 development checks but 0/6 on a
fresh independent holdout, so the development result did not generalize. See
the [final long-task evaluation](long-task-diagnostics-2026-10-15.md).

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

The recovery policy uses one normal Luna replan, the ComplexityGate, and at
most one high-reasoning replan. Laya may provide shadow observations where it
is configured; it does not route recovery or executable actions. Unavailable
reasoning asks the user or stops within configured bounds.

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

## M8. Vision fallback (OPT-IN ON-DEMAND ROUTING IMPLEMENTED; PRIVACY REDACTION PENDING)

Bounded viewport screenshot capture and structured Luna vision are available
through an opt-in on-demand route for explicit visual tasks whose needed
information is absent from browser-native semantics. Findings remain advisory
and Luna still selects a bounded semantic action. Vision is disabled by default
and blocked in privacy-first/offline modes until screenshot sanitization is
implemented. Semantic observation remains primary.

## M9. Browser-code escape hatch (ISOLATED SEMANTIC TRANSFORMS IMPLEMENTED)

An opt-in isolated QuickJS capability transforms bounded Rust-owned semantic
data with source, heap, stack, timeout and result bounds. It has no live DOM,
browser handles, network, filesystem or shell. Dispatch and transient result
inspection are integrated with the graph and provider boundary. The extension
rejects generic model-authored `Runtime.evaluate` and `Runtime.callFunctionOn`
requests. See the
[`browser-code boundary`](../architecture/browser-code.md) and
[`ADR-014`](../decisions/ADR-014-isolated-semantic-data-transforms.md).
Live-page model code remains disabled under ADR-011.

## M10. Privacy mode (OPTIONAL MODES AND ENCRYPTED CHECKPOINTS IMPLEMENTED)

Standard, privacy-first, and offline policy modes exist. Privacy-first uses
pattern-based redaction plus a request-scoped token vault that restores values
only into typed action text/value fields. External provider calls pass through
one provider boundary. API credentials use OS keyring storage or an explicit
environment override, with no plaintext-file fallback. Checkpoints use
authenticated encryption with a keyring or owner-only local-key fallback.
Pattern detection is incomplete. Screenshot redaction remains pending, so
privacy-first/offline block visual inference. Privacy is optional and is not
mandatory middleware for every action.

## M11. Product surface (LOCAL SOFTWARE ACCEPTANCE PASSED; LIVE LUNA PENDING)

The CLI, doctor checks, safe run metadata, preview-first checkpoint cleanup,
MV3 side-panel UI, protocol tests, and user docs are implemented.
`AgentRuntime` supports cooperative pause, resume, and stop at safe graph
boundaries. The side panel now dispatches task controls and receives
content-minimal lifecycle events. A Linux Native Messaging host relay
validates caller origin, checks owner-only Unix socket permissions, and
forwards bounded JSON frames. The authenticated service connects its attached
browser session through the shared Rust CDP core into the Python task runtime,
and supports task submission and confirmation responses. Real packaged-extension
tests exercise Native Messaging, the shared Rust core, task controls, traces,
high-risk denial, native side-panel creation and cancellation on tab/host loss.
Provider responses in these tests are deterministic fixtures; they do not
establish live Luna task success. A Linux installer builds the mixed
Rust/Python package and extension locally. The full multi-tab demo passes with
fixture decisions, source-bound working memory and pause/resume. Final local
release builds, wheel installation and checksum checks passed. The
[validation record](productization-validation.md) separates this software
evidence from live-provider acceptance and agent reliability.

## M12. Benchmark hardening (BROADER VALIDATION DEFERRED)

The frozen local V8 task-mix evaluation is complete: 16/18 development checks
and 0/6 independent holdout checks. The development score did not generalize.
Representative broader long-horizon evaluation and reproducible comparative
claims remain outstanding. See the [final evaluation report](long-task-diagnostics-2026-10-15.md).
