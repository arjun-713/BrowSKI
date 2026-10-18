# BROWSKI 2.0 migration checkpoint

**Status: TARGET / IN MIGRATION.** Updated 2026-10-18.
Canonical plan: root `ARCHITECTURE_PLAN.md`; workflow: root `AGENTS.md`.

## Repository and user constraints

Branch `migration/browski-v2`, clean starting base `6a80e9b`. Phase 0 committed
as `41fb40d`; phase 1 as `164c036`; phase 3 contract as `6b66bfa`. Legacy Luna/LangGraph/Rust and the extension are retained for
rollback; new engines do not use that graph or Rust executor.

Machine verified: i5-8350U, 8 logical CPUs, 15 GiB usable RAM; Chrome and uv.
No CUDA assumption. **User correction: only Laya may run locally.** Do not
install/run a local generative model. An interrupted Qwen download and its
llama.cpp runtime were removed before any inference. The user then explicitly
authorized small bounded OpenAI debugging calls after offline checks and
confirmed reuse of the existing key. Routine paid inference remains off;
no hosted fallback or Jev request has been made.

## Phase status

| Phase                   | State                                                   | Evidence / next gate                                                                    |
| ----------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| 0 Guidance              | Complete — `41fb40d`                                    | Branch, canonical plan, AGENTS and ADR-022 validated                                    |
| 1 Browser Use baseline  | Complete — `164c036`                                    | Wikipedia URL + visible heading checked independently; 2 authorized API calls           |
| 2 Extension integration | Next major phase                                        | Actual side-panel submission, ownership, approval, controls/results                     |
| 3 Fast contract         | Complete — `6b66bfa`                                    | Same semantic request through Laya/Jev adapters, malformed-input and policy tests       |
| 4 Local Laya            | Complete for navigation slice; next commit records hash | Real one- and two-click tasks, zero generative calls; forms/text unsupported            |
| 5 Jev/switching         | Partial                                                 | HTTP adapter/offline contracts; CLI/config/settings integration unfinished; no live key |
| 6 Debug controls        | Pending                                                 | Product engine/provider controls and trace mapping                                      |
| 7 Reliability           | Partial experiment only                                 | Premature DONE rejected; two small cases do not prove general reliability               |
| 8 Cleanup               | Pending                                                 | No legacy deletion until replacement regression gates                                   |

## Latest evidence

- General: official Browser Use Agent opened
  `https://en.wikipedia.org/wiki/Alan_Turing`, returned Alan Turing, fresh DOM
  confirmed exact URL and visible H1. 2 model calls, 1 navigation, 2 steps,
  26,046.71 ms, zero recorded provider errors. This is a small integration gate,
  not a public-site success benchmark. No more paid calls needed for this gate.
- CPU Laya v19s pinned to `cklxx/laya-browser` revision
  `645cf366a2ae35f1086e8c20eff48f909bb49206`. Root checkpoint, not obsolete v10s.
  Reviewed model code SHA-256 is checked before local-only model loading.
  PyTorch CPU wheel, no training/MLX/CUDA. Weights/profile/logs stay ignored.
- Saved-decision probe: 635/655 ms inference, 6,680 ms model/tokenizer loading,
  correct candidate twice. These are two samples, not a latency distribution.
- Initial real local task pair: 1/2 passed. Multi-step run proposed DONE after
  Botany, before Leaf structure; verifier returned partially_completed.
  With DONE excluded while explicit outcome checks remain false, both cases
  passed. One two-click run took 27,612.96 ms, 3 decisions, 1 freshness recovery,
  zero generative calls. These runs overlapped software validation; do not
  present them as isolated hardware performance measurements.
- `make test` (UV_NO_SYNC=1 to retain installed optional extras): Rust 146 passed,
  1 ignored; Python 676 passed, 35 opt-in skips. Later targeted engine suite:
  21 passed, 2 live-Laya skips, including real Browser Use navigation, offline
  Agent responses, false-DONE refusal and in-flight cancellation.
- Latest combined engine/CLI validation: **50 passed** (including both live Laya
  tasks, official Agent with offline responses, cancellation and existing CLI
  regressions). Repeated two-click Laya run: 24,966.70 ms task, 8,544.12 ms
  model/tokenizer loading, 2,187.95 MiB peak inference-process RSS; per-decision
  1,288/1,177/1,438 ms while validations ran. Warm and cold scopes differ.
- `make lint` passed: Rust fmt/clippy, Python Ruff lint/format and strict
  Pyright (0 errors/warnings). Latest General-only browser suite: 5 passed,
  including false-completion and cancellation.

## Reproduction

From repository root:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --project python --extra engines --extra laya-cpu --extra dev
BROWSKI_ENGINE_E2E=1 python/.venv/bin/pytest python/tests/test_engine_integration.py
BROWSKI_LAYA_E2E=1 python/.venv/bin/pytest -s python/tests/test_fast_engine.py -k live_laya
UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 make test
UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 make lint
```

General smoke (paid, explicit; do not run routinely):

```sh
uv run --project python --no-sync --env-file .env browski general   'Open https://en.wikipedia.org/wiki/Alan_Turing and report the visible main article heading.'   --allow-paid-api --max-calls 2 --max-steps 3   --verify-url https://en.wikipedia.org/wiki/Alan_Turing --verify-heading 'Alan Turing'
```

Browser Use is pinned to upstream `aa093a843da5edbf323c0b4145c9b6a0db3ecde8`
(version 0.13.13). Released 0.13.11 pins an OpenAI SDK incompatible with legacy
Luna. The upstream fix relaxes that pin; no SDK downgrade or resolution override.
Optional dependencies add substantial transitive packages; only 73 packages were
installed in this Linux development environment. The lock also records other
platforms. No Ollama daemon was installed or launched.

## Known limits and next exact action

General currently exposes navigation/reading tools, not consequential clicks,
forms, arbitrary browser code, uploads or file tools. Its model final text never
proves completion. Only explicit caller-owned URL/H1 checks can return completed;
other tasks return an unverified/partial outcome. Cancellation and budgets are
covered with offline inference and real Chrome.

Fast currently offers same-site links only. It refuses candidate overflow,
requires fresh semantic identity before clicking, bounds recovery and does not
silently invoke text generation. The upstream tokenizer emits a regex warning;
it has not been suppressed or silently changed from the released checkpoint.
No general Laya calibration or unseen public-site reliability is established.

Next: commit the validated Laya navigation slice, then connect engine selection
to the product lifecycle and extension.
only with its tested implementation, then connect task-level engine selection
to the existing product lifecycle. The extension debugger relay is not a native
CDP WebSocket; start with an isolated managed-browser product task rather than
assuming attachment compatibility. Preserve approvals and legacy rollback.

Local Fast commands (from repository root):

```sh
python/.venv/bin/browski prepare-laya
python/.venv/bin/browski fast 'Open the requested article.' \
  --start-url http://127.0.0.1:PORT/index.html \
  --verify-url http://127.0.0.1:PORT/article.html --verify-heading 'Article'
```

The Fast provider defaults to Laya. `--provider jev --allow-paid-api` selects
Jev only when `TYPESAFE_API_KEY` is supplied; without a key it fails clearly and
suggests local Laya. No live Jev result is claimed. Provider config/settings UI
and mid-task switching are not implemented yet. `browski run/task` and the
extension still use the legacy runtime until phase 2; do not describe the new
Fast CLI as the default product task route.
