# AGENTS.md — instructions for coding agents working in this repository

Before major work, read this file, [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md),
and [CODE_QUALITY.md](CODE_QUALITY.md) completely. The architecture plan governs
design and the roadmap, the quality guide governs implementation quality,
and this file governs repository workflow. Non-trivial architecture changes
require an ADR (see “When to write an ADR”).

## 1. Project mission

Build BROWSKI, an open-source browser agent runtime for reliable short and
long-running browser tasks. Current runtime policy is GPT-6 Luna for all
executable decisions, Laya as non-executing shadow only, and Jev disabled.
GPT-6 Luna is the only generative reasoning model in the baseline. OpenAI
credentials are needed to run model-backed tasks. Doctor must never perform
model inference or make external provider requests. Local loopback health
checks, including Laya availability, are permitted.

Primary metric: **end-to-end task completion**. Everything else (steps,
tokens, latency, cost, recovery rate) is secondary but measured — see
`docs/benchmarks/evaluation-plan.md`.

## 2. Architectural principles (all 20 — do not dilute)

1. End-to-end task completion is the primary metric.
2. Browser-native semantics (DOM + accessibility + layout) before expensive vision.
3. Vision is a complementary sensor, not the universal representation.
4. Every browser action must be verifiable.
5. A tool call completing without exception does NOT mean the action succeeded.
6. Failures have structured types and evidence (`FailureKind` + evidence).
7. Recovery is a subsystem, not a prompt instruction.
8. Retries are bounded (Rust: `MAX_MECHANICAL_RETRIES = 3`; Python replan bounds).
9. The agent must detect stagnation and repeated actions.
10. Browser state must never be trusted indefinitely (generations, reacquisition).
11. Element references survive small page changes where possible (fingerprints).
12. Long-running tasks require explicit working memory and task state.
13. Raw historical context must not grow without bound.
14. Prefer deterministic browser operations once intent is known.
15. GPT-6 Luna selects bounded executable actions; Rust performs deterministic
    browser mechanics and verification.
16. Decision and reasoning providers are replaceable through the shared
    `DecisionProvider` and `ReasoningProvider` domain interfaces.
17. The browser core must not know which LLM provider is used.
18. Browser infrastructure and reasoning stay separate (Rust ≠ Python).
19. Benchmarks exist from the beginning.
20. Do not claim an improvement without measuring it.

## 3. Language ownership

| Language | Owns | Must never own |
|---|---|---|
| Rust (`crates/`) | CDP, browser events, DOM/AX state, element identity, diffing, action execution, verification primitives, low-level recovery, perf-sensitive infra | LLM calls, prompts, provider logic, planning, memory |
| Python (`python/`) | Agent loop, planning, orchestration, memory, task state, high-level recovery, decision/reasoning adapters, eval/benchmarks | CDP transport, DOM collection internals, raw browser process management |
| TypeScript (`extension/`, `web/`) | Extension, trace viewer, browser-facing UI/SDK | Agent internals, browser automation core |
| Bun | Dev scripts/tooling where measurably faster | The browser core |
| Go | Nothing yet; allowed later for isolated high-throughput services with benchmarks | Anything without a benchmark-backed justification |

Dependency direction: **Python may depend on Rust bindings. Rust must not
depend on Python domain logic. Frontend communicates through public
APIs/events, never by linking agent internals.** Full rationale:
`docs/architecture/language-boundaries.md`, ADR-001.

## 4. Directory ownership

- `crates/browser-core/` — `BrowserSession`, lifecycle, tab/frame coordination.
- `crates/cdp/` — typed CDP access, transport, Chrome specifics.
- `crates/observation/` — `SemanticSnapshot` / `SemanticElement` shapes + collection.
- `crates/element-registry/` — `ElementRef`, fingerprints, reacquisition, generations.
- `crates/executor/` — `BrowserAction` vocabulary + validated execution. No reasoning.
- `crates/verification/` — postconditions, before/after comparison, evidence.
- `crates/recovery/` — low-level mechanical retries (bounded). No replanning.
- `crates/telemetry/` — `TraceEvent` envelope, timing, traces.
- `crates/browser-code/` — isolated, bounded semantic-data transforms; no live
  browser, network, filesystem, or shell capability.
- `crates/python-bindings/` — PyO3 surface (`browser_agent._core`) only.
- `python/src/browser_agent/agent|planning|memory|progress|recovery/` — runtime.
- `python/src/browser_agent/decisions/` — bounded `DecisionProvider` contract, Laya/Jev adapters, calibration, and shadow comparison. Laya output must not authorize execution.
- `python/src/browser_agent/reasoning/` — `ReasoningProvider` contract and the GPT-6 Luna adapter.
- `python/src/browser_agent/tools/` — model-facing typed tools bridging to Rust.
- `python/src/browser_agent/extension/` — authenticated local service, Native
  Messaging framing, transport broker and product lifecycle.
- `python/src/browser_agent/providers/` — authoritative outbound privacy gates.
- `python/src/browser_agent/persistence/` — encrypted checkpoints, safe run
  metadata, aggregate counters and retention.
- `extension/` — WXT/React product UI and owned-tab debugger proxy. It must not
  duplicate the browser semantic engine or agent decisions.
- `benchmarks/`, `tests/`, `examples/`, `docs/`, `scripts/` — as named.

Do not create directories with no expected ownership or purpose.

## 5. Shared contract rules

- Canonical browser-side schemas live in Rust (`observation`, `executor`,
  `verification`, `recovery`, `telemetry`); Python mirrors them in
  `python/src/browser_agent/_types.py` (Pydantic v2).
- Do not duplicate browser state models in multiple languages beyond this one
  sanctioned mirror.
- Do not lock schemas prematurely where research is pending — mark `TODO`
  with the deciding milestone.
- Serialized shapes (`SemanticSnapshot`, `TraceEvent`, binding APIs) are
  versioned per `docs/protocols/versioning.md`. Non-trivial migration ⇒ ADR.

## 6. Dependency rules

- No language or major dependency without a written benefit (performance,
  reliability, ecosystem, integration, speed, deployment). Record in an ADR.
- LangGraph is allowed in Python orchestration as specified by the active
  BROWSKI architecture plan. Never add it to the Rust browser core. Do not add
  LangChain or CrewAI without an architecture decision.
- Do NOT add Redis, Postgres, vector DBs, Kubernetes, Docker Compose,
  microservices, auth systems, or cloud infra without a benchmark-backed need.
- Keep new dependencies minimal (“no 30 dependencies for later”).
- Laya and TypeSafe SDK are optional provider extras; neither may become a
  required dependency of the base browser runtime. Jev is disabled by current
  runtime policy. Do not call Jev without a later explicit architecture change.
- Commit lockfiles: `Cargo.lock`, `python/uv.lock`, `extension/package-lock.json`.

## 7. Test requirements

- Every crate: unit tests for its logic (`cargo test`).
- Browser behavior: integration/smoke tests that launch real Chromium
  (`crates/browser-core/tests/smoke.rs`, `python/tests/test_session_smoke.py`).
- Python contracts: `python/tests/test_contracts.py` for schemas, bounds
  (memory caps, retry bounds), and registries.
- Run the full gates before finishing: `make test`, `make lint`.
- Extension changes additionally require `npm run check` in `extension/` and
  actual packaged-Chromium smoke tests (`make test-extension-e2e`). Provider
  fixtures in software tests do not establish live-model task success.
- If launching Chromium in an environment is impossible, say so explicitly —
  do not silently skip browser tests.

## 8. Benchmark requirements

- Every behavior/performance change needs a measurement plan referencing
  `docs/benchmarks/evaluation-plan.md`.
- Track: task success, partial completion, steps, LLM calls, tokens, cost,
  latency, action/verification failure rates, recovery and stagnation rates.
- Never claim superiority or “improvement” without numbers.

## 9. When to write an ADR

Write one (`docs/decisions/ADR-NNN-<slug>.md`) when you: change a shared
contract non-trivially; add/remove a language or major dependency; choose a
browser-control approach; alter cross-language APIs; or pick between credible
architectural options. Read ADR-001 and ADR-002 first.

## 10. How to add a language or major dependency

1. State the measurable benefit and the alternatives considered.
2. Prove the current stack inadequate (benchmark, failed spike, or ecosystem gap).
3. Write the ADR; keep interfaces language-independent where practical.
4. Update this file’s ownership tables and `docs/architecture/language-boundaries.md`.

## 11. How to change cross-language APIs

1. Check `docs/protocols/versioning.md` for the compatibility class.
2. Patch version: additive/compatible. Minor/major or schema change: ADR +
   migration notes + version bump (`TRACE_SCHEMA_VERSION`,
   snapshot `schema_version`, binding `__version__` as applicable).
3. Update Rust types, the Pydantic mirror, bindings, and tests together —
   never one side alone.

## 12. How to handle failures

- Give each failure a `FailureKind`, evidence, and the owning component (see
  `docs/development/failure-taxonomy.md`).
- Low-level (stale node, detached frame, nav race): bounded mechanical retry
  in Rust, then escalate with evidence.
- High-level (bad plan, stagnation, auth, site block): replan/alternate
  strategy/escalate in Python.
- Never swallow errors; never retry without a bound; never treat an
  unverified tool call as success.

## 13. No-go architectural patterns

- Do not put LLM calls in Rust `browser-core` (or any crate).
- Do not let providers manipulate browser internals directly.
- Do not put browser automation inside prompts instead of tools.
- Do not use screenshots as the only page representation.
- Do not add retries without explicit limits.
- Do not treat a successful click call as verified success.
- Do not duplicate browser state models in multiple languages (one mirror only).
- Do not change a shared contract without an ADR if migration is non-trivial.
- Do not put LangGraph, LangChain, or CrewAI in the Rust browser core. LangGraph
  orchestration belongs to Python and follows the active BROWSKI architecture
  plan.
- Do not create another browser abstraction without proving the current one inadequate.
- Do not add a new language without justification.
- Do not touch the CDP socket outside `crates/cdp/src/transport.rs` — only
  the transport owns the socket; everything else uses typed commands/events.
- Do not hold a lock guard across `.await`, and never `if let` directly on
  `tabs.read().await…` when the body locks again (scrutinee temporaries live
  through the body and self-deadlock). Resolve to an owned value first.
- Do not build the old mandatory pipeline (screenshot → local detector → OCR
  → ScreenGraph → privacy → LLM → executor) as the default; browser-native
  grounding comes first, perception/privacy are optional modules.
- Do not add a frontend, extension capability, local visual model, training,
  or cloud infrastructure unless it is part of an explicitly authorized
  product milestone. The current productization scope authorizes an extension
  UI/bridge, on-demand vision, browser-code policy, privacy modes, and local
  service packaging; preserve the Rust/Python ownership boundaries.

## 14. Current provider and product status

- GPT-6 Luna is the only provider allowed to select executable actions.
- Laya comparisons are shadow telemetry only and never change Luna's choice.
- Jev is disabled and is not required for development or runtime operation.
- The extension is a UI, browser attachment layer, and permission broker. It
  must not implement agent reasoning, semantic state, verification, recovery,
  memory, or provider routing.
- Mark product capabilities as implemented, partial, or planned based on
  executable integration evidence. A provider contract or UI scaffold is not
  an end-to-end feature.

## 15. Definition of done (scaffold)

Cargo builds · Python installs via `uv` · bindings build · Python drives Rust
· Chromium launches · navigation + title observation work · clean shutdown ·
Rust + Python tests pass · lint/typecheck pass · CI exists · README/AGENTS/
architecture docs/ADRs/benchmark plan/roadmap/failure taxonomy exist · no
large unneeded features built.
