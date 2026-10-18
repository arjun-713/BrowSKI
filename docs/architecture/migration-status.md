# BROWSKI 2.0 migration checkpoint

**Status: TARGET / IN MIGRATION.** Updated 2026-10-18.
Canonical design: root `ARCHITECTURE_PLAN.md`; workflow: root `AGENTS.md`.

## Verified starting state

- Clean `main`, base commit `6a80e9b`; dedicated branch `migration/browski-v2`.
- Legacy Luna/LangGraph/Rust runtime and extension remain untouched.
- Machine: Intel i5-8350U, 8 logical CPUs, 15 GiB usable RAM; about 8.2 GiB
  available at inspection. Chrome `/usr/bin/google-chrome`, `uv` installed.
  Ollama not on PATH. No assumption of CUDA or Apple MLX support.
- No inference calls, model downloads or dependency changes in phase 0.

## Phase status

| Phase                   | State                     | Evidence / next gate                                                  |
| ----------------------- | ------------------------- | --------------------------------------------------------------------- |
| 0 Guidance              | Validated, commit pending | Canonical plan, AGENTS, ADR-022 and this checkpoint; link/diff checks |
| 1 Browser Use baseline  | Next                      | Local generative model + real independently verified browser task     |
| 2 Extension integration | Pending                   | Real extension task, ownership/approval/progress/results              |
| 3 Fast contract         | Pending                   | Equivalent requests through normalized adapters                       |
| 4 Local Laya            | Pending                   | Live CPU browser-tuned inference and verified Fast task               |
| 5 Jev/switching         | Pending                   | Offline Jev contracts, no credentials assumed                         |
| 6 Debug controls        | Pending                   | Settings/trace UI and provider visibility                             |
| 7 Reliability           | Pending                   | Fresh task evidence, no increased false success                       |
| 8 Cleanup               | Pending                   | Replacement regression gates before legacy removal                    |

## Latest validated commit and commands

Last successful pre-migration commit: `6a80e9b`.
Phase 0 commit will be recorded here in the next checkpoint update; a commit
cannot embed its own hash. Inspect `git log --oneline migration/browski-v2`.
Working inspection: `git status --short --branch`, `lscpu`, `free -h`.
Documentation validation: `git diff --check` plus local Markdown link checks.
No current runtime/test success is claimed by this documentation-only phase.

## Decisions and blockers

- ADR-022 authorizes library-backed Python browser control for new engines.
- Default target is local Laya Fast + separate local text generation. General
  uses official Browser Use. No paid calls or Browser Use Cloud by default.
- Browser Use Agent and Jev Ultrafast do not share one native agent interface.
- Extension `chrome.debugger` proxy is not a browser-level CDP endpoint; prove
  compatible attachment/ownership before exposing General in the product.
- Local generative runtime/model and current Laya checkpoint need verification.
- Existing historical Laya results do not validate the selected browser-tuned
  checkpoint. Jev live testing is unavailable without user-supplied credentials.

## Next exact action

Commit validated phase 0. Inspect pinned Browser Use APIs/dependencies, local
inference availability and released Laya checkpoint metadata. Establish the
smallest reproducible local Browser Use task with independent page evidence,
bounded execution, structured events and cleanup; do not delete legacy code.
