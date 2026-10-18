# ADR-022: Local-first General and Fast engine migration

Date: 2026-10-18 · Status: accepted for implementation; TARGET / IN MIGRATION

## Context

The user explicitly authorizes BROWSKI 2.0, replacing the Luna/LangGraph/Rust
execution path where functional evidence supports it. Legacy V8 scored 16/18
on development tasks and 0/6 on the independent holdout. That is evidence of
poor task generalization, not evidence that Rust itself is defective. Routine
debugging must not consume paid inference. The development CPU is i5-8350U,
16 GB RAM; local model capacity and latency need measurement.

## Decision

Use the official Browser Use Python Agent for General and an indexed
Jev-ultrafast-style Fast policy with a versioned Laya/Jev contract. Laya is the
local Fast default; Jev is opt-in and not required for installation or tests.
Text generation is separate, local by default. Enforce paid inference opt-in.
One controller per session; task-level engine selection precedes optional
handoff. Preserve the existing extension/product surface and legacy rollback.

This supersedes exclusive Rust browser ownership in ADR-001/002 and exclusive
Luna execution in ADR-008 for new engines. It does not enable legacy Laya shadow
responses as actions or make the existing Jev adapter validated. See
`ARCHITECTURE_PLAN.md` for actual versus target responsibilities.

## Alternatives and benefit to measure

- Harden the existing candidate/Luna/graph path: lowest migration cost, but
  does not meet the authorized local-first execution architecture.
- Browser Use for everything: less custom policy, but discards the required
  typed local Laya/Jev decision path.
- Fork/vendor all upstream repositories: faster initial copying, substantially
  higher maintenance and duplicated browser ownership. Reject unless a small
  maintained dependency is insufficient.

Browser Use provides a maintained agent/browser integration ecosystem and local
model adapters. Its transitive dependency and CPU model costs must be measured,
not assumed acceptable. Keep optional engine/inference extras. Read upstream
licenses and preserve attribution for any adapted source. No new language,
cloud service or orchestration framework is authorized by this decision.

## Consequences and acceptance

Python library-backed browser infrastructure is now permitted behind an engine
adapter. Rust/PyO3 and LangGraph stay as rollback until equivalent application
behavior is verified. Extension debugger transport compatibility is unresolved
at phase 0. First prove a managed-browser local task. Then prove actual
extension integration and owner isolation. DONE/final text require independent
outcome proof. Record migration phase gates, commands, blockers and commits in
`docs/architecture/migration-status.md`. No general reliability claims without
fresh end-to-end measurements, including unseen tasks and false success.

## User clarification — 2026-10-18

Only Laya may run locally on this development machine. Text generation is
therefore disabled by default; no local generative model is a prerequisite.
The user permits small bounded OpenAI debugging after offline validation and
explicitly confirmed reuse of the existing key. This supersedes the original
local-text default above. Routine paid inference and all paid fallback stay off.
