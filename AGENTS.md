# AGENTS.md — instructions for coding agents working in this repository

Before major work, read this file, [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md),
and [CODE_QUALITY.md](CODE_QUALITY.md) completely. The architecture plan governs
design and the roadmap, the quality guide governs implementation quality,
and this file governs repository workflow. Read
[the migration checkpoint](docs/architecture/migration-status.md) before resuming
BROWSKI 2.0 work. Non-trivial architecture changes
require an ADR (see “When to write an ADR”).

## 1. Project mission

Build BROWSKI, an open-source browser agent that completes real tasks with
independently verified outcomes. **BROWSKI 2.0 is TARGET / IN MIGRATION**;
see the canonical architecture plan and ADR-022. Existing executable code is
still the legacy Luna/LangGraph/Rust runtime until replacement gates pass.

Target: official Browser Use for the General engine; a small Jev-ultrafast-style
Fast loop with interchangeable typed Laya (default, local) / Jev (optional,
hosted) providers. Text generation is separate and disabled on this machine: the user permits
only Laya as a local model (2026-10-18 correction). The user permits small bounded OpenAI debugging runs after offline validation,
using the existing key (explicitly confirmed); routine paid inference stays off. Hosted
inference requires explicit provider selection, credentials and paid-API opt-in.
Never silently fall back to a paid model, including from legacy entry points.
The model powering Codex is not a BROWSKI runtime inference endpoint.
Doctor must not infer or call external providers; loopback health checks are OK.

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
15. Engines select bounded executable actions; code validates actions and
    independently verifies outcomes. Rust owns these mechanics only in legacy mode.
16. Decision and reasoning providers are replaceable through the shared
    `DecisionProvider` and `ReasoningProvider` domain interfaces.
17. The browser core must not know which LLM provider is used.
18. Browser infrastructure and reasoning stay separate; library adapters keep
    Browser Use mechanics out of product orchestration.
19. Benchmarks exist from the beginning.
20. Do not claim an improvement without measuring it.

## 3. Language ownership

| Language                          | Owns                                                                                                                                              | Must never own                                     |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Rust (`crates/`)                  | Legacy CDP/browser core; retained for rollback until replacement gates pass                                                                       | LLM calls, prompts, provider logic                 |
| Python (`python/`)                | Product lifecycle, engine/library adapters, Laya/Jev decisions, local text generation, verification, evals; legacy orchestration during migration | Competing controllers for the same browser session |
| TypeScript (`extension/`, `web/`) | Extension, trace viewer, browser-facing UI/SDK                                                                                                    | Agent internals, browser automation core           |
| Bun                               | Dev scripts/tooling where measurably faster                                                                                                       | The browser core                                   |
| Go                                | Nothing yet; allowed later for isolated high-throughput services with benchmarks                                                                  | Anything without a benchmark-backed justification  |

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
- `python/src/browser_agent/decisions/` — legacy decision contract/adapters and shadow comparison; do not silently enable legacy shadow output as an executor.
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
- LangGraph remains a legacy dependency; do not require it in the new engine
  lifecycle. Browser Use is authorized by ADR-022. Do not introduce another
  orchestration framework or plugin platform.
- Do NOT add Redis, Postgres, vector DBs, Kubernetes, Docker Compose,
  microservices, auth systems, or cloud infra without a benchmark-backed need.
- Keep new dependencies minimal (“no 30 dependencies for later”).
- Keep inference dependencies optional for installation/doctor/offline tests.
  Laya is the target default for Fast mode. Jev is optional, disabled by default,
  and live execution remains unverified without credentials. No paid calls
  during routine debugging. Pin released/browser-tuned checkpoints; no training
  prerequisite. Do not adopt the Apple MLX port on Fedora/Linux.
- Commit lockfiles: `Cargo.lock`, `python/uv.lock`, `extension/package-lock.json`.

### Extension versioning

Every extension update must increment its version before rebuilding:

- Small changes: increment the patch by `0.0.1` (for example, `0.1.0` → `0.1.1`).
- Major rewrites only: increment the minor by `0.1.0` and reset the patch
  (for example, `0.1.3` → `0.2.0`).
- Keep `extension/package.json` and the root package version in
  `extension/package-lock.json` consistent. Rebuild the extension so its
  generated Chrome manifest carries the new version.
- Display the manifest version in the side panel; do not hardcode a version label.

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

## 14. BROWSKI 2.0 migration rules — TARGET / IN MIGRATION

- General and Fast are separate engines, selected for the whole task initially.
  One active controller per browser session. No unproven mid-task engine handoff.
- Browser Use Agent is the General engine, with separately configured generative
  inference. On this machine, local generative models are disabled; the user
  authorizes only small explicit OpenAI debugging runs. Cloud browsers are not required.
- Fast uses versioned semantic state + typed questions + stable candidates.
  Laya/Jev adapters normalize status, choice/score, probabilities, latency,
  provider identity, failures and abstention. Browser actions, task state,
  verification and benchmarks never branch on vendor-specific responses.
- Text generation is separately configured; Laya/Jev are not arbitrary text
  generators. Provider calibration differs; confidence is not outcome proof.
- Provider switching applies to the next task; a safe decision-boundary switch
  is optional. Never switch in the middle of an action. Missing Jev credentials
  must give a clear error and identify Laya as the local alternative.
- Preserve the React extension, local lifecycle/events, approval controls,
  history, cancellation and tab ownership where useful. Determine a supported
  Browser Use attachment path before changing extension browser transport.
- Completion needs independent evidence; DONE/final prose is only a proposal.
  Target terminal statuses: completed, partially_completed, blocked, failed,
  cancelled. Bound steps, time, recovery, history and model calls.
- Keep legacy Luna/LangGraph/Rust execution available for rollback. Remove it
  only after actual replacement behavior and regression gates pass. New
  defaults must not accidentally invoke legacy hosted inference.
- Use a handful of meaningful existing/parameterized suites. Real browser
  tasks and unseen cases establish success; fixtures establish contracts only.
  Record task/false-success rates, task/decision latency, actions, recoveries,
  generative calls, provider errors and memory where meaningful. Keep weights,
  profiles, screenshots, traces and generated logs out of Git.
- Subagents are optional, sparse and independent (normally at most two).
  Only use GPT-6.1 Sol with High effort, explicitly configured and verifiable;
  otherwise work in the main session. Give disjoint file ownership. No agent
  swarm or redundant review for tiny changes. Main agent owns guidance,
  architecture, shared interfaces, validation and Git integration.
- Work on a dedicated migration branch; preserve unrelated changes. The user
  explicitly authorizes one meaningful commit per successful phase. Validate
  its gate, review the diff, update status and stage only phase files. Never
  commit failed experiments as completed phases; no empty commits or pushes.
- Root AGENTS + ARCHITECTURE_PLAN + one migration checkpoint are the continuity
  documents. Update after each successful phase. Record the previous phase's
  commit in the next checkpoint update (a commit cannot contain its own hash).
- Mark capabilities implemented/partial/planned from executable evidence.
  Debug capture remains opt-in, bounded, owner-only and separate from durable
  state. Never persist credentials, hidden reasoning or screenshots in it.

## 15. Definition of done (scaffold)

Cargo builds · Python installs via `uv` · bindings build · Python drives Rust
· Chromium launches · navigation + title observation work · clean shutdown ·
Rust + Python tests pass · lint/typecheck pass · CI exists · README/AGENTS/
architecture docs/ADRs/benchmark plan/roadmap/failure taxonomy exist · no
large unneeded features built.
