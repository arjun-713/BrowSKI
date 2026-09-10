# Roadmap

Every phase has a measurable gate. Do not start the next phase’s headline
work until the gate is met (docs and small refactors may proceed in parallel).

## 0. Scaffold + research (current)

Build the repo, contracts, docs, and minimal executable slice.
Gate: the Definition of Done in `AGENTS.md` §14 — `make test` and `make
lint` green, Chromium launch/navigate/observe/close proven from Python.

## 1. Browser runtime

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

## 2. Observation + element identity

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

## 3. Executor + verification

All `BrowserAction` variants executed and verified with evidence on
synthetic pages (forms, navigation, dialogs, scrolling).
Gate: 100% verification agreement with ground truth on the synthetic suite
(no false SUCCESS).

## 4. First autonomous loop

UNDERSTAND→…→RECOVER on short tasks (≤10 steps) with one provider.
Gate: ≥70% task success on an internal 20-task synthetic set.

## 5. Memory + progress

`WorkingMemory`, `TaskState`, stagnation detection, SQLite checkpoints,
`resume`/`inspect` commands.
Gate: a 30-step task survives a mid-run restart and completes; memory stays
bounded (assert on event-cap tests).

## 6. Recovery

Full failure taxonomy wired end-to-end; low-level bounded retries plus
high-level replan/alternate-strategy/escalation.
Gate: recovery success rate measured on injected-failure suite; stagnation
rate drops vs Phase 4 baseline.

## 7. Vision / code escape hatch

Screenshot fallback via multimodal providers; deterministic code-execution
actions for structured extraction.
Gate: vision-gated tasks (canvas/custom widgets) succeed where Phase 4 fails,
with vision-call rate reported (lower is better).

## 8. Provider hardening

Capability detection per model, structured-output paths, cost/latency
tracking, local-model support.
Gate: same task set passes on ≥3 providers (one local) with cost/latency
tables published.

## 9. Benchmarks

BrowserGym integration first, then WebArena-family suites; reports in
`benchmarks/reports/`.
Gate: published task-success numbers with full metric set; CI runs the
synthetic suite.

## 10. Privacy / extension / procedural memory

Token vault, PII/secret detectors, sanitized screenshots, optional browser
extension, trace viewer, procedural memory.
Gate: secret-redaction suite passes (no raw secret reaches a mocked remote
endpoint); trace viewer renders a recorded run.
