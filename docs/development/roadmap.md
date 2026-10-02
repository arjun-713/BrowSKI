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

Validation on 2026-10-02: `cargo fmt --all -- --check`,
`cargo clippy --workspace --all-targets -- -D warnings`, and
`cargo test --workspace` passed. The M3 integration suite has 22 tests; the
workspace run also passed 15 M2 integration tests, 12 runtime stress tests,
and browser smoke tests. This gate does not claim Python agent integration.

## M4. LangGraph agent runtime (NEXT)

Implement typed agent state, observe/execute/verify workflow nodes,
checkpointing, and resume. Initially use a fake reasoning provider to validate
graph behavior and local browser fixtures before adding cloud integrations.

## M5. System One decisions

Add Laya as the preferred local CPU provider and TypeSafe Jev as a switchable
cloud fallback/comparison behind `DecisionProvider`. Support bounded Choice,
Score, yes/no probability, semantic verification, recovery classification,
and progress checks with provider-specific calibration.

## M6. GPT-6 Luna + adaptive reasoning

Add the only generative reasoning provider in the baseline and a
`ComplexityGate`; deep reasoning is exceptional and de-escalates after the
difficult decision is resolved.

## M7. Memory, progress, and recovery

Add bounded working memory, task milestones, progress and stagnation checks,
checkpoint/resume behavior, and explicit recovery budgets. Verify long-horizon
and interrupted workflows against local fixtures.

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
