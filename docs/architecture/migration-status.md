# BROWSKI 2.0 migration checkpoint

**Status: TARGET / IN MIGRATION.** Updated 2026-10-19.
Canonical plan: root `ARCHITECTURE_PLAN.md`; workflow: root `AGENTS.md`.
This checkpoint replaces the accumulated phase diary; detailed decisions and
historical validation remain in ADR-022–030, the evaluation plan and Git history.

## Repository and constraints

Branch `migration/browski-v2`, starting base `6a80e9b`. Last committed phase:
**`526669b` — approved Fast form workflows**. Owned-tab navigation (ADR-030) is
implemented and validated in this phase. Record its commit in the
next checkpoint update; a commit cannot contain its own hash.

Machine: i5-8350U, 8 logical CPUs, 15 GiB usable RAM, Fedora, Chrome and uv.
**Only Laya may run locally; no local generative model or training.** An earlier
interrupted Qwen download/runtime was removed before inference. The user
explicitly permits small bounded OpenAI debugging after offline checks and
confirmed reuse of the existing key. Four requests were used across the initial
General and product gates; none in subsequent reliability slices. Routine paid
inference stays off. No hosted fallback or live Jev request has been made.

## Completed slices and remaining phases

| Slice                   | Commit / state | Verified scope                                                                   |
| ----------------------- | -------------- | -------------------------------------------------------------------------------- |
| 0 Guidance              | `41fb40d`      | Branch, canonical plan, AGENTS, ADR-022                                          |
| 1 General baseline      | `164c036`      | Official Browser Use, verified Wikipedia heading, bounded OpenAI                 |
| 3 Fast contract         | `6b66bfa`      | Shared typed Laya/Jev contract and normalized responses                          |
| 4 CPU Laya              | `848cd06`      | Browser-tuned local decisions, real navigation, bounded subprocess               |
| 2 Product bridge        | `3d62ab2`      | Packaged extension, lifecycle, ownership and results                             |
| 5 Jev/switching         | `84aac2a`      | Offline Jev validation; next-task settings switching; live Jev unverified        |
| 6 Diagnostics           | `0ebefdb`      | Provider/action errors, metrics, bounded safe capture and saved-input comparison |
| 7 Destination grounding | `4a52b9e`      | Complete private href freshness; Fast v2 with saved-v1 migration                 |
| 7 General approvals     | `a5685be`      | Approved indexed click and quoted-literal ordinary text                          |
| 7 Fast literals         | `99c702a`      | Approved text fields, fresh values and all-field proof                           |
| 7 Native controls       | `d62b15a`      | Native dates/single-select, validity, option identity, replacement reread        |
| 7 Stagnation            | `1085895`      | Unrelated body-text changes do not count as structural progress                  |
| 7 Form workflow         | `526669b`      | One approved named transition, one invocation, exact fresh receipt               |
| 7 Owned tabs            | Validated here | Native popup, full target identity, verified focus, bounded races                |
| 7 Broader workflows     | Pending        | Source-to-field provenance, richer goal checks, auth/session coverage            |
| 8 Cleanup               | Pending        | Retain Legacy until replacement behavior and evaluation gates pass               |

## Current implementation and limits

- Product defaults: **Fast/Laya, text disabled, paid false**. Configuration and
  sidebar settings apply to the next task; changes during a task are refused.
  `engines/product.py` dispatches CLI/extension tasks without the Legacy graph
  or Rust executor. General/Fast each own one isolated task browser; there is
  no mid-task engine handoff, personal-cookie import or second controller.
- General uses the official Browser Use Agent and separately configured OpenAI
  inference, only with explicit paid/privacy/credential gates. Product budget:
  four requests, five steps, 90 seconds; explicit General CLI defaults to three
  requests. Navigation/read and verified owned-tab selection are available.
  Indexed click and exact quoted-literal ordinary text require a sidebar approval.
  Native date/select, arbitrary code, files and synthesized inputs are excluded.
- Fast v2 offers same-host links, CLICK/role-tab candidates and approved exact
  user literals for ordinary text, native ISO dates and single-select fields.
  Values never come from provider prose. Unique labels, native constraints and
  fresh post-write values/selected-option identity are required. One read can
  reacquire a replaced control without repeating the write. Every observation
  recomputes all field proof; arbitrary disappearance invalidates it.
- One explicit quoted click/press may follow verified fields (ADR-029), with a
  new approval and unmet caller outcome criteria. Only that invoked transition
  preserves the completed field stage. It executes once, then only bounded
  receipt reads occur. Query/fragment values compare exactly; plain path
  trailing-slash tolerance remains. Custom controls/multiple named actions are
  not enabled. CLI without approval support blocks unmet interactions.
- Owned tabs use full SDK target IDs, actual actor-page evidence and independently
  checked focus/destination. Fast refuses more than eight owned pages and
  reuses exact already-open popup destinations. Closed, changed or not-ready
  targets consume the existing recovery budget. General resolves displayed
  short IDs only when unique among owned targets. Task cleanup closes all tabs.
  This is tab navigation, not source-value memory, auth transfer or resumability.
- Task lifecycle retains pause, cancel, approval IDs/expiry, history/replay and
  progress. Stop invalidates pending approval and wins a simultaneous return.
  Approval is bound to fresh page/target/native state. Managed checkpoints and
  manual continuation are not implemented; Legacy remains explicit rollback.
- Completion needs caller-owned URL/visible-H1 checks plus supported field and
  transition obligations. DONE/prose alone is unverified. These checks are not
  generic proof of every natural-language goal or server business state.
- Doctor inspects configuration/local health without inference or hosted calls.
  Debug capture is opt-in, bounded and owner-only. No secrets/screenshots/hidden
  reasoning in durable metadata. Keep generated logs/profiles/weights ignored.

## Pinned dependencies and model evidence

Browser Use: upstream `aa093a843da5edbf323c0b4145c9b6a0db3ecde8`, version 0.13.13.
The upstream SDK pin fix preserves compatibility with Legacy Luna; no SDK
resolution override or downgrade. Optional extras are already installed here.

Laya: `cklxx/laya-browser` revision
`645cf366a2ae35f1086e8c20eff48f909bb49206`, root v19s checkpoint. Reviewed model-code
SHA is checked before local-only loading. PyTorch CPU, float32, four inference
threads, bounded warm subprocess per task; no MLX/CUDA/training. One earlier
measured process peaked at 2,187.95 MiB RSS; overlapping validation means it is
not an isolated machine-performance benchmark. The upstream tokenizer regex
warning remains visible; the tokenizer/checkpoint were not silently modified.

Both providers receive equivalent Fast semantic requests and typed questions.
Jev's raw Score shape is normalized separately. Missing Jev credentials fail
clearly and suggest local Laya; they never trigger a fallback. `compare-fast`
requires explicit paid opt-in and credentials before loading saved input/model.
Live Jev accuracy/latency and provider calibration remain unverified.

## Measured task evidence

- Initial General: verified Wikipedia URL/H1, two calls, one navigation,
  26.05 s. Packaged General also passed offline and with a bounded two-request
  live run. These are integration examples, not broad autonomous accuracy.
- Frozen navigation first look on `0ebefdb`: **4/4 completed, 0/4 false success**,
  13 decisions, nine clicks, four freshness reacquisitions, no generative calls
  or provider errors. Mean engine time 16.25 s, median inference 809 ms. These
  cases are now spent regressions, never unseen again. Manifest SHA-256:
  `c2cb313ea04549a3562bc719d1f52645babde46b2a028f52551d7ffea3480da1`.
- Native controls: first local date/select task completed in 15.77 s, two
  decisions/actions, no generative calls/errors. Wrong replacement/removed-field
  cases remain unverified; the latter previously reproduced false completion.
- Approved Name/City/Save: before, partial after two inputs; CPU Laya completed
  three actions/decisions in 14.42 s, zero hosted/generative calls/errors.
  Packaged sidebar passed with three approvals. GET and actual POST/303/GET
  regressions enforce exact receipt values and one submission invocation.
- Tab task: the fixture baseline blocked after three repeated opener clicks
  without selecting Reference; the new adapter completed in three actions with
  the same fixture decisions. Separately, first CPU Laya completed three
  actions/four decisions, one verified
  source focus, exactly two tabs, two recoveries, 18.10 s, no generative calls or
  provider errors. Packaged default-Fast tab task passed (25.89 s including
  harness), without Legacy attachment or hosted credential lookup. This is
  development evidence, not an unseen success-rate or speed claim.

## Latest validation and unresolved gates

- Previous committed phase: **741 Python passed, 103 opt-in skips**; isolated
  focused engine/provider/workflow gate **137 passed**; packaged gate **24
  passed, four spent-navigation skips**. Lint/strict typing passed.
- Current phase full Python: **743 passed, 114 opt-in skips, 79.92 s**. Initial
  focused browser/model run: **149 passed, one failed, 187.93 s**. The failure
  was an exact total-recovery assertion after the wrong replacement date was
  correctly rejected with one write; one extra pre-action freshness recovery
  occurred. The test now requires exactly one TYPE_TEXT replacement reread,
  one write/approval and total counter/event agreement. Its targeted rerun
  passed. The final focused rerun passed **150 tests in 187.19 s**, including
  real CPU Laya and General with offline inference. Full packaged gate:
  **25 passed, four spent-navigation skips, 276.99 s**, with CPU Laya enabled.
  `make lint` passes (Rust fmt/clippy, Ruff lint/format, strict Pyright 0 errors).
  Extension `npm run check` passes: TypeScript, ESLint, Prettier, **74 software
  tests** and build. The build ran after packaged execution, using unchanged
  extension sources and version 0.2.3.
- Owned-tab mechanical cases passed **9 tests** (one Laya opt-in deselected):
  fixture navigation, closed/changed target, step bound, same-URL distinct IDs,
  no-op SDK focus, General owned switch and missing ID. Shared provider contract
  checks passed **60 tests**, including equivalent role-tab requests.
- No Rust, dependencies or extension assets changed. Package/lock/built manifest
  remain **0.2.3**. Never rebuild while packaged tests are using the manifest.
- **Historical Rust stalls, not reproduced in the current run:** earlier `make test` stalled in unchanged
  `stress_cross_tab_cycles_100`; a serialized 360-second retry also timed out.
  The identical isolated 100-cycle case passed in 12.24 s. The current combined
  run completed **146 Rust tests, one ignored**, including all 12 stress tests
  in 24.34 s. Its 180-second outer cap then stopped Python at roughly 84%
  (exit 124), with no reported Python failure. The standalone full Python rerun
  then passed **743 tests, 114 opt-in skips, 79.92 s**. Both component gates
  pass; do not call that bounded combined command a pass. The historical
  stall's cause is still unknown; a passing rerun does not establish a fix.
- An earlier overlapping model-heavy run timed out in native Laya before any
  decision/action (104 passed, one failed). Recent memory pressure/full swap
  was observed afterward; cause is unproven. Isolated focused gates then passed
  136/136 and 137/137. Normal production timeouts remain unchanged. Serialize
  model-heavy validation and retain this evidence; no hidden retries.

## Reproduction

From repository root, with existing prepared extras/model and Chrome:

```sh
BROWSKI_ENGINE_E2E=1 BROWSKI_LAYA_E2E=1 BROWSKI_GENERAL_LIVE_DEBUG=0 \
  python/.venv/bin/pytest python/tests/test_engine_integration.py \
  python/tests/test_fast_workflows.py python/tests/test_fast_engine.py \
  python/tests/test_task_values.py python/tests/test_engine_cross_page.py
PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" \
  UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 BROWSKI_LAYA_E2E=1 \
  BROWSKI_GENERAL_LIVE_DEBUG=0 make test-extension-e2e
UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 make test
UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 make lint
```

No dependency installation, model download or paid call is needed for these
checks on this prepared checkout. Run the model-heavy commands sequentially.
Extension software/build checks use `npm run check` in `extension/`, separately
from packaged execution. General live debugging remains opt-in; no new paid run
is needed for the tab gate.

## Next exact action

Implement one bounded source-to-field workflow using the SDK-owned tabs and
explicit provenance, not a second controller or arbitrary provider text.
Revalidate source/target across approval, reject ambiguous/hidden/sensitive or
changed facts, and prove actual field/receipt outcomes through the packaged UI.
Reuse the cross-page suite/HTTP fixture. Broader authentication/session state,
generic goal coverage, fresh unseen evaluations and Legacy replacement remain
open. Keep the overall migration goal active; do not claim production readiness.
