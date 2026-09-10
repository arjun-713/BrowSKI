# AGENTS.md — instructions for coding agents working in this repository

Read this file before any other action. It is normative: where it conflicts
with a plausible alternative, this file wins. Non-trivial deviations require
an ADR (see “When to write an ADR”).

## 1. Project mission

Build a general-purpose open-source browser agent that completes short and
long-running browser tasks reliably, using any supported LLM provider (API key
or local model). Product experience: install package → provide key/model →
state a natural-language task → agent completes it autonomously.

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
15. LLMs resolve ambiguity, not mechanical reasoning.
16. Models/providers are replaceable (`providers/base.py` is the domain API).
17. The browser core must not know which LLM provider is used.
18. Browser infrastructure and reasoning stay separate (Rust ≠ Python).
19. Benchmarks exist from the beginning.
20. Do not claim an improvement without measuring it.

## 3. Language ownership

| Language | Owns | Must never own |
|---|---|---|
| Rust (`crates/`) | CDP, browser events, DOM/AX state, element identity, diffing, action execution, verification primitives, low-level recovery, perf-sensitive infra | LLM calls, prompts, provider logic, planning, memory |
| Python (`python/`) | Agent loop, planning, orchestration, memory, task state, high-level recovery, provider abstraction, eval/benchmarks | CDP transport, DOM collection internals, raw browser process management |
| TypeScript (`web/`) | Extension, trace viewer, browser-facing UI/SDK | Agent internals, browser automation core |
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
- `crates/python-bindings/` — PyO3 surface (`browser_agent._core`) only.
- `python/src/browser_agent/agent|planning|memory|progress|recovery/` — runtime.
- `python/src/browser_agent/providers/` — OUR interface (`base.py`); LiteLLM is one adapter.
- `python/src/browser_agent/tools/` — model-facing typed tools bridging to Rust.
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
- Do NOT introduce LangChain / LangGraph / CrewAI into the core architecture.
- Do NOT add Redis, Postgres, vector DBs, Kubernetes, Docker Compose,
  microservices, auth systems, or cloud infra without a benchmark-backed need.
- Keep new dependencies minimal (“no 30 dependencies for later”).
- Commit lockfiles: `Cargo.lock`, `python/uv.lock`.

## 7. Test requirements

- Every crate: unit tests for its logic (`cargo test`).
- Browser behavior: integration/smoke tests that launch real Chromium
  (`crates/browser-core/tests/smoke.rs`, `python/tests/test_session_smoke.py`).
- Python contracts: `python/tests/test_contracts.py` for schemas, bounds
  (memory caps, retry bounds), and registries.
- Run the full gates before finishing: `make test`, `make lint`.
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
- Do not introduce LangChain/LangGraph/CrewAI into core architecture.
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
- Do not build large frontends, extensions, local VLM inference, training, or
  cloud infra in early milestones.

## 14. Definition of done (scaffold)

Cargo builds · Python installs via `uv` · bindings build · Python drives Rust
· Chromium launches · navigation + title observation work · clean shutdown ·
Rust + Python tests pass · lint/typecheck pass · CI exists · README/AGENTS/
architecture docs/ADRs/benchmark plan/roadmap/failure taxonomy exist · no
large unneeded features built.
