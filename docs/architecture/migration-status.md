# BROWSKI 2.0 migration checkpoint

**Status: TARGET / IN MIGRATION.** Updated 2026-10-18.
Canonical plan: root `ARCHITECTURE_PLAN.md`; workflow: root `AGENTS.md`.

## Repository and user constraints

Branch `migration/browski-v2`, clean starting base `6a80e9b`. Phase 0 committed
as `41fb40d`; phase 1 as `164c036`; phase 3 contract as `6b66bfa`, phase 4 navigation as `848cd06`, phase 2 product integration as `3d62ab2`, phase 5 switching as `84aac2a`, phase 6 diagnostics as `0ebefdb`, phase-7 navigation as `4a52b9e`, managed approval as `a5685be`, Fast literal fields as `99c702a`, native controls as `d62b15a`. Legacy Luna/LangGraph/Rust and the extension are retained for
rollback; new engines do not use that graph or Rust executor.

Machine verified: i5-8350U, 8 logical CPUs, 15 GiB usable RAM; Chrome and uv.
No CUDA assumption. **User correction: only Laya may run locally.** Do not
install/run a local generative model. An interrupted Qwen download and its
llama.cpp runtime were removed before any inference. The user then explicitly
authorized small bounded OpenAI debugging calls after offline checks and
confirmed reuse of the existing key. Routine paid inference remains off;
no hosted fallback or Jev request has been made.

## Phase status

| Phase                   | State                                                             | Evidence / next gate                                                                         |
| ----------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 0 Guidance              | Complete — `41fb40d`                                              | Branch, canonical plan, AGENTS and ADR-022 validated                                         |
| 1 Browser Use baseline  | Complete — `164c036`                                              | Wikipedia URL + visible heading checked independently; 2 authorized API calls                |
| 2 Extension integration | Navigation gate committed — `3d62ab2`                             | Packaged General (offline + bounded live), local two-click Laya, results and ownership       |
| 3 Fast contract         | Complete — `6b66bfa`                                              | Same semantic request through Laya/Jev adapters, malformed-input and policy tests            |
| 4 Local Laya            | Complete for navigation slice — `848cd06`                         | Real one- and two-click tasks, zero generative calls; phase 7 adds approved text fields      |
| 5 Jev/switching         | Complete for offline/selection gate                               | 25 contract/policy/dispatch checks; settings round trips; live Jev unverified without key    |
| 6 Debug controls        | Complete for navigation diagnostics                               | 75 focused checks, packaged General/Laya 2/2, safe capture and saved-input comparison wiring |
| 7 Reliability           | Navigation/approval/text committed; native-control gate validated | Dates/selects/replacement/disappearing-field checks; broader workflows/tabs still open       |
| 8 Cleanup               | Pending                                                           | No legacy deletion until replacement regression gates                                        |

## Baseline evidence (earlier phases)

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
BROWSKI_LAYA_E2E=1 python/.venv/bin/pytest -s python/tests/test_engine_integration.py -k live_laya
BROWSKI_ENGINE_E2E=1 BROWSKI_LAYA_E2E=1 python/.venv/bin/pytest python/tests/test_fast_workflows.py
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

General exposes navigation/reading and a conservative sidebar-only form slice:
each indexed click and exact quoted-literal text replacement requires approval
and page/target revalidation (ADR-025). CLI without an approval sink remains
read-only. Dates, selects, uploads, credentials, arbitrary browser code and
source-to-field synthesis are not enabled. Model final text never proves completion. Only explicit caller-owned URL/H1 checks can return completed;
other tasks return an unverified/partial outcome. Cancellation and budgets are
covered with offline inference and real Chrome.

Fast offers same-site links and approved quoted-literal ordinary text, native
date and single-select fields (ADR-026/027). Every requested field must match
fresh values and native validity as well as the final URL/H1. Removed fields
invalidate prior proof. CLI without approval support blocks unmet requirements.
Custom controls, submit buttons, source transfer and persistent sessions remain
open. It refuses candidate overflow,
requires fresh semantic identity before clicking, bounds recovery and does not
silently invoke text generation. The upstream tokenizer emits a regex warning;
it has not been suppressed or silently changed from the released checkpoint.
No general Laya calibration or unseen public-site reliability is established.

Next: phase-7 fresh reliability tasks and action coverage; preserve Legacy until its capabilities are replaced. Phase-2 navigation
integration is committed; its aggregate Rust regression issue remains open. General
and Fast use separate managed Chrome profiles, not the extension debugger relay.
The sidebar states this; personal tab authentication is not transferred. Existing
Legacy approvals/rollback remain; General has a bounded approved form slice and
Fast also has an approved literal native-field slice.

Local Fast commands (from repository root):

```sh
python/.venv/bin/browski prepare-laya
python/.venv/bin/browski fast 'Open the requested article.' \
  --start-url http://127.0.0.1:PORT/index.html \
  --verify-url http://127.0.0.1:PORT/article.html --verify-heading 'Article'
```

The Fast provider defaults to Laya. `--provider jev --allow-paid-api` selects
Jev only when `TYPESAFE_API_KEY` is supplied; without a key it fails clearly and
suggests local Laya. No live Jev result is claimed. Engine/provider configuration is now exposed in the sidebar and TOML; changes
apply to the next task, with in-flight changes refused. `browski run/task` use the
configured engine. Both require explicit URL/H1 evidence for verified completion;
without it, no model DONE can return success. Mid-task provider handoff is not offered.

Phase-2 evidence (2026-10-18):

- Extension 0.2.0 → authenticated Native Messaging → official Browser Use Agent →
  real Chrome → fresh URL/H1 check → completed sidebar result: passed with offline
  HTTP responses, then with live OpenAI under a hard two-request cap. The latter
  took 33.20 s including the extension harness; it is one controlled task, not a
  benchmark. No additional paid debugging calls are needed for this gate.
- Packaged Fast/Laya Botany → Leaf structure: passed in 42.31 s including harness,
  CPU inference only, paid APIs disabled. This repeats the development task, not an
  unseen case. General navigation tools cannot submit forms; Fast is same-site links.
- Full packaged extension gate: 15 passed, 1 opt-in Laya skip, 158.34 s. The skipped
  Laya case was separately run live and passed. Existing attached execution,
  approvals, session correlation, stop and privacy regressions remain covered.
- New focused checks cover unsafe task URLs, local defaults, paid denial despite
  credentials, pause/resume/stop boundaries, provider configuration round trips,
  quoted checkpoint paths, and terminal replay. Extension software checks passed;
  380px packaged sidebar rendered and inspected without horizontal overflow.
- Full `make test` stalled in the unchanged Rust `stress_cross_tab_cycles_100`
  test, also under a serialized 360-second bounded retry (exit 124). The isolated
  identical 100-cycle test passed in 12.24 s. Cause remains unresolved; no Rust
  source changed. This is an outstanding aggregate regression gate, not proof
  that the new engines failed or that Legacy is safe to delete.
- A broader Python run caught the old diagnostic constructing a paid Legacy
  provider under Fast defaults. Fixed: active managed configuration is validated
  without creating a provider, and local mode does not need an OpenAI key. Its
  six tests pass. The initial full run hit its overall time cap; the clean rerun
  passed **691 tests, 38 opt-in skips in 230.13 s**. This precedes phase-6 changes;
  do not present it as a current full-suite result for later edits.
- `make lint` passed after the diagnostic fix (Ruff, Rust fmt/clippy, strict Pyright).
  The latest extension `npm run check` passes with 74 software tests. No further
  paid inference is needed for the phase-2 gate.

Phase-5 acceptance: the same product dispatch calls the same `run_fast` interface
for configured Laya/Jev. Offline factories do not claim browser task success.
Missing Jev credentials fail before the loop and never load Laya as a fallback.
Jev HTTP tests cover equivalent semantic state, ordered score rubrics, malformed
answers, explicit opt-in, credential-safe redirects, invalid endpoints and an
in-flight timeout. 25 focused tests pass; no live Jev request has been made.
Settings changes require no runtime restart and affect the next task.

Remaining: phase 7 needs fresh failure-category benchmarks and broader actions, phase 8 cannot delete useful Legacy capabilities
before replacements pass. No live Jev execution is claimed.

Phase-6 acceptance — `0ebefdb`: General HTTP/network errors are counted
separately from browser action errors; earlier `history.errors()` incorrectly
mixed them. Events include model identity, inference timing, action/verification
and recovery information. Final sidebar summaries include steps/actions,
generative calls, provider errors, recovery count, task latency and verification.

`engines/product.py` binds opt-in sanitized capture for managed CLI/extension
runs. Detailed Fast capture saves versioned inputs/normalized decisions;
`browski compare-fast` validates a bounded saved request and compares Laya/Jev
without browser actions. It requires explicit paid opt-in and Jev credentials
before reading input or loading models. Live Jev remains unverified.

Validation: 75 focused tests passed with real Browser Use + offline inference,
HTTP-500 classification, capture permissions/replay, CLI gates and comparison
wiring. Two live-CPU Laya cases were opt-in skips in that run; the
packaged multi-step Laya task passed separately. Packaged General (offline inference) and local multi-step
Laya both passed after trace changes (2/2, 61.02 s including harness). The new
result text was rendered and inspected at 380 px with no horizontal overflow.
No more paid OpenAI requests were used. Final `make lint` passed after a
new fixture annotation was corrected (Rust fmt/clippy, Ruff and strict Pyright). The aggregate Rust stall remains open.

Phase-7 navigation slice — `4a52b9e`:

- Frozen first-look manifest `benchmarks/synthetic/v2-navigation-first-look.json`
  ran through the real extension on runtime `0ebefdb`: 4/4 completed, 0/4 false
  successes, 13 local decisions, 9 clicks, 0 generative calls/provider errors.
  Details and SHA are in `docs/benchmarks/evaluation-plan.md`; raw verified public
  fixture metrics are ignored in `benchmarks/reports/v2-navigation-first-look.json`.
  These cases are now spent; further runs are regressions, not unseen evidence.
- An initially inconclusive href mutation test was stabilized to isolate the
  change. Old code then clicked Astronomy after Botany's href changed without
  changing its backend ID or label. Final task verification refused success.
  The new complete-destination fingerprint refuses that click (real Chrome
  regression: 1 wrong click before → 0 wrong clicks after).
- ADR-024 introduces Fast contract v2 with optional bounded destination context
  for both providers; v1 saved requests migrate on read. Model-facing href omits
  query/fragment. Full private href participates only in hashing. Malformed,
  credential and non-HTTP navigation is rejected; General validates model URLs
  before the official tool executes. Rust/Native Messaging schemas unchanged.
- Managed E2E tests moved to `python/tests/extension/test_managed_e2e.py`, reusing
  the existing Native Messaging fixture. Make's packaged gate includes both
  files. A fresh default-Fast/Laya task passed with **no Legacy browser
  attachment**, no hosted credential lookup and a natural task-link starting URL.
- V2 rerun: the same four cases completed 4/4 with zero generative calls. This
  establishes regression coverage, not fresh evaluation or a speed improvement.
  An overlapping extension rebuild removed its manifest before three fixtures
  could start; only those fixture errors were rerun after the build completed.
  All affected cases passed. Keep builds and packaged test execution sequential.
- Latest validation: **706 Python tests passed, 51 opt-in skips, 136.99 s**;
  **73 focused engine/contract/CLI tests passed, 2 live-Laya skips**; all seven
  managed packaged cases passed across completed first-run cases and the
  affected-fixture rerun.
  Full normal packaged gate: **15 passed, 6 opt-in skips, 164.14 s**. The skipped
  CPU/first-look paths were separately exercised live. `npm run check` and
  `make lint` passed. Extension source, lock and manifest match **0.2.1**.
  No additional paid OpenAI or live Jev requests were used.

At that checkpoint, native primitives were the next action; the bounded slice
below now covers them. Broad forms/tabs/auth/resumability remain open. The
aggregate Rust stress-suite stall remains unresolved, while its isolated case
passed. Retain Legacy and keep the migration goal active.

Phase-7 managed approval slice — `a5685be`:

- General's actual Browser Use indexed click/input tools now use the existing
  sidebar approval card and authenticated protocol. A unique task-local future
  waits for exactly one pending action; no second executor or Legacy graph is
  created. Session/approval IDs are checked. Deny, Stop and 60-second expiry
  cannot authorize the action; cleanup clears the card. These are not durable
  checkpoints. A prior Pause remains effective after the card is consumed.
- Input is limited to exact quoted task literals, ordinary main-document text
  fields and replacement input. A fresh native field-value read checks typing.
  Dates/selects/files/passwords/append and synthesis are not enabled. Every new
  General interaction needs approval; CLI without a sink remains read-only.
  Task outcomes still require caller-owned URL/H1 evidence, not model prose.
- Fresh pre/post-approval state includes complete bounded main-document HTML,
  live field values, URL, document epoch, target geometry and stable node/target/
  frame identity. The first packaged run exposed transient CDP session IDs
  changing with identical node/page hashes. Stable browser target identity
  fixed that false block without accepting a changed page. The pinned actor
  also required upstream DOM.getDocument before element inspection, including
  after input. No independent CDP transport/executor was added (ADR-025).
- Six real-Chrome input cases pass: approved typing, denial, live property
  mutation, append refusal, invented-text refusal and password-field refusal.
  Four packaged form variants pass with **offline HTTP model responses**:
  approved local save completed with exact URL/H1; Deny and changed field were
  blocked; Stop cancelled without the pending click. This is integration proof,
  not autonomous General accuracy. The initial Stop fixture had the wrong
  button selector (`Stop task` versus the actual `Stop`); corrected and rerun.
- Latest gates: **711 Python tests passed, 61 opt-in skips, 136.96 s**;
  **55 engine/contract tests passed, 2 live-Laya skips**, plus the final
  pause/approval regression in the full Python run. Full packaged gate with
  CPU-Laya opt-ins enabled: **21 passed, 4 spent-navigation opt-in skips,
  361.73 s**. Both real local Laya paths passed. This overlapped regression
  work and is not a performance comparison. `make lint` passed; extension
  `npm run check` passed with 74 software tests and a successful build.
  Source/lock/manifest all carry **0.2.2**. No new paid OpenAI or live Jev calls.

The next slices extend Fast fields; source transfer, tab/auth/session workflows,
durable managed resume and richer goal coverage remain open. Keep the migration
goal active. This slice changes no Rust source. Retain Legacy until replacement
gates pass.

Phase-7 Fast literal text-field slice — `99c702a`:

- Extracted only the bounded quoted set/fill/type grammar and label normalization
  from Legacy into `task_literals.py`; no Legacy graph/provider imports in Fast.
  Strict Fast intent rejects conflicts, incomplete/unquoted/blank/overlong field
  instructions, control characters and overflow. Quoted literal contents cannot
  become new instructions. Legacy retains soft abstention; its 11 value tests
  and the full Python regression pass.
- Fast offers unmet uniquely named ordinary text fields as TYPE_TEXT candidates.
  Values come from user intent, never a provider response. Both adapters pass the
  same typed-input contract fixtures. Reuses ADR-025's actual Browser Use input
  tool, per-action approval, current target/page binding and fresh value read.
  Approval cards now use accessible names. No new serializer/version change:
  Fast v2 already defines TYPE_TEXT. No paid fallback or local generative model.
- Completion now requires final URL/H1 **and all requested fields**. The first
  live Laya development task filled Name/City (2 actions/decisions, 24.66 s,
  1717/1811 ms decisions, 0 recoveries/provider errors/generative calls).
  This is one development timing, not an unseen benchmark or speed claim.
- Real-Chrome tests cover fixture and actual CPU Laya completion, a live value
  mutation invalidating the decision (0 typing actions), masked input refusing
  verification (1 invoked action), duplicate labels and missing fields (partial,
  never completed). No candidates means bounded abstention without inference.
  CLI without an approval sink blocks unmet fields before inference. Stop wins
  a simultaneous engine-return race. Task profiles still close at task end.
- Actual packaged default-Fast field task passed without Legacy attachment or
  hosted credential lookup, with two distinct approvals. Full packaged suite:
  **22 passed, 4 spent-navigation opt-in skips, 321.84 s**, CPU-Laya enabled.
  Latest full Python: **723 passed, 69 opt-in skips, 166.72 s**. Final focused
  real-engine/provider/Legacy suite: **88 passed, 164.51 s**; latest six field
  cases also passed separately. `make lint` and extension `npm run check` pass
  (74 extension software tests); package/lock/manifest all **0.2.3**.
  No new paid OpenAI or live Jev calls. Raw development logs remain in /tmp;
  the frozen navigation manifest has not been changed or reused as unseen data.

Phase-7 Fast native controls and fresh proof — `d62b15a`:

- ADR-027 retains Browser Use's executor and Fast v2. Native dates use TYPE_TEXT;
  single-select uses SELECT. Both provider adapters receive equivalent state.
  Strict user literals, unique labels, per-action approval and fresh target/page
  binding remain mandatory. General's ordinary text tools share live validity
  checks, but General does not enable date/selection actions yet.
- Real SDK probes returned without errors for an impossible date (empty actual
  value), an out-of-range date (invalid), and Blue matching Red's option value.
  New native reads require exact value, validity and selected option identity.
  Visible-label-first resolution chooses an unambiguous SDK token; disabled,
  multiple, ambiguous, unsupported and oversized controls cannot supply proof.
- Replacement-date case reproduced blocked after one write; one bounded semantic
  reread now completes with two actions and one read recovery, without repeating
  the date write. A wrong replacement value remains blocked. Missing candidates
  receive at most three settle/reobserve retries, without provider inference.
- Final review reproduced a false completed result after a later select removed
  an already verified date. Field proof is now rebuilt every observation: that
  case returns partially_completed after two actions, with no false completion.
- First real CPU-Laya two-control development run passed: 15.77 s engine time,
  two actions/decisions, 1582/1050 ms decisions, no recoveries/provider errors/
  generative calls. This is a development timing, not unseen or comparative
  evidence. The task also passed through the actual packaged default-Fast
  sidebar, two approvals, no Legacy attachment or hosted credential lookup.
- Reviewed-source gates: **725 Python tests passed, 86 opt-in skips, 130.65 s**;
  **95 focused engine/provider/workflow tests passed, 174.81 s**, including real
  CPU Laya; full packaged gate **23 passed, 4 spent-navigation skips, 297.09 s**.
  `make lint` passed (Rust fmt/clippy, Ruff lint/format, strict Pyright 0 errors).
  Existing engine test functions were preserved when moving field cases.
  No additional paid OpenAI or live Jev calls. No extension assets/dependencies
  changed; package/lock/manifest remain 0.2.3. Frozen navigation data is unchanged.
  Four compact migration test boundaries remain; field cases moved into the
  functional workflow suite, reusing the existing HTTP fixture.

Phase-7 Fast stagnation — validated in this commit:

- ADR-028 reproduces an ineffective receipt click changing an unrelated counter:
  four clicks exhausted the outer five-iteration budget despite one retry being
  allowed. Static text already stopped after two. Neither falsely completed.
- A separate structural signature plus fresh visible H1 now drives stagnation.
  Full body-text observations still guard decision freshness; approvals and
  final outcome checks are unchanged. Both fixture variants stop within at most
  two clicks. Actual click counters and false verification events are checked.
  Initial missing-candidate retries share the budget, so one observed ticking
  run stopped after one click. Recovery events now expose these attempts.
- Full Python: **725 passed, 88 opt-in skips, 128.37 s**. Focused real-browser/
  provider/workflow suite: **97 passed, 188.52 s**. Final strict typing required
  handling the existing optional page-evidence result; the final targeted
  stagnation pair passed again. `make lint` passes with strict Pyright 0 errors.
  Full packaged gate: **23 passed, 4 spent-navigation skips, 316.10 s**, with real
  CPU Laya enabled. Package/lock/built manifest remain 0.2.3; no rebuild needed.
  No additional hosted requests, dependencies, schema or extension changes.

Next exact action: reproduce unrelated dynamic-page freshness/approval blocks
before changing conservative fingerprints. Submit buttons,
source transfer, tabs/auth, generic outcome coverage and persistent managed
sessions remain open. Keep Legacy and the overall migration goal active. The
aggregate Rust stress-suite stall remains an outstanding gate; no Rust source
changed in these slices. Do not call the migration or product production-ready.
