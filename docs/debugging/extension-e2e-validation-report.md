# Extension reliability validation

Status: in progress. This is an evidence ledger, not a completion claim.

Scope: October 16 results below concern the explicit **Legacy attached-browser**
path. Current General/Fast defaults and managed-task results are governed by
[the architecture plan](../../ARCHITECTURE_PLAN.md). The October 22 follow-up
below separates these paths; Legacy Laya shadow policy is not the new Fast policy.

## Previous 24-task evidence

The saved latest comparison contains **16/24**, not the 18/24 cited in the
debugging brief: 16/18 development cases and 0/6 independent V3 holdout cases.
These were live Luna runs in managed headless Chromium. They did not exercise
the real extension. Independent fixture graders checked browser outcomes;
model `DONE` alone was insufficient.

Sources: `benchmarks/task_mix/results/2026-10-15/comparison.csv` and
[long-task diagnostics](../development/long-task-diagnostics-2026-10-15.md).
The frozen task definitions and graders remain unchanged. Those results cannot
be reused as evidence of attached-browser reliability.

## Deterministic tests before API calls

| Scope | Current result | Limit |
| --- | --- | --- |
| Service, doctor, safe exception regression | 40 passed | Software boundary checks |
| Authenticated diagnostics socket | 3 passed | No real browser in these tests |
| Attached SPA rerender | Passed | Direct shared session through actual extension (Mode B) |
| Attached controlled overlay | Passed | Mode B; verifies interactability changes and completion |
| Attached ten-action journey | Passed | Mode B; ten successful Rust verifications |
| Extension worker reload | Passed | Panel-driven pending decision cancels without action |
| Runtime bridge restart | Passed | No replay; fresh explicit attachment succeeds |
| Identical A/B/C differential tasks | 5 passed, 1 failed | Click-created target-blank tabs remain unsupported in attached mode |
| User's production Chrome observation | Passed after transport repair | Authenticated doctor, no inference; full task acceptance is separate |
| Deep DOM through real panel | Passed | 80 nested wrappers reproduce the former Rust parser limit |
| Crowded page with real provider boundary | Passed in diagnostic run | Actual panel submission, 450 elements, projected context, click, verification and completion |
| Long extension connection | Passed 9,978 sequenced messages | UUID cache remained at 4,096; one deterministic-provider task, not a reliability benchmark |

## October 16 follow-up failures and repairs

The user's run `764cd96d-e2cc-480b-b259-ccd2b7bdbd19` reached
successful Google observation, then a local provider context limit. No OpenAI
request was sent. Commit `88aca25` fits relevant semantic elements within the
existing 32,000-character limit while preserving policy, typed targets and
source evidence. Irreducible context receives a specific local error.

The crowded-page regression then exposed the connection's lifetime
4,096-message cap. The pre-fix validator recorded exactly that count and
`extension message replay window is exhausted`. Commit `24b3382` adds
sequenced outgoing envelopes in extension 0.1.7, preserving bounded replay
state and rejecting older packets without a lifetime message limit. Legacy
unsequenced connections retain the original cap.

The successful diagnostic used the actual packaged extension, authenticated
Native Messaging, shared Rust engine, real provider boundary, and deterministic
provider responses. It completed the click task with verified page evidence at
about **75 seconds**, after 9,978 sequenced messages. This is a correctness
result; the latency is a significant remaining limitation on crowded pages.
The trace shows repeated full semantic observations and thousands of geometry
requests. No claim of acceptable interactive performance follows from this run.

Safe evidence is stored locally under
`debug-logs/extension-reliability-20261016/`:

- `message-budget-rejection.json`
- `transport-timeline-0.1.7.jsonl`
- `transport-timeline-diagnostic.log`

The fixture initially used a default submit-type button, which correctly
triggered the conservative form-submission gate. It now explicitly uses
`type="button"`, matching the intended non-submitting action. A prior run
displayed a confirmation phase without a rendered approval card; this was
not established as a repaired confirmation defect. Existing dedicated approval
regressions remain the evidence for that separate flow.

## Live Luna and observation performance

The same 360-card fixture and task, `Click Reveal result.`, were then exercised
through the actual side panel with the real configured `gpt-6-luna` API.
Every run completed with one API call and deterministic browser evidence.
No Jev calls or Laya execution decisions were used.

| Runtime state | Task time | Luna time | Calls | Cached input tokens |
| --- | ---: | ---: | ---: | ---: |
| Sequenced bridge, original observation matching, debug build | 90.293 s | 6.620 s | 1 | 0 |
| Exact backend match retained, debug build | 41.444 s | 4.616 s | 1 | 2,295 |
| Exact backend match retained, release build | 35.608 s | 5.900 s | 1 | 2,295 |

The observation change honors the registry's unique live backend identity
instead of computing every semantic candidate score again. This also prevents
an unrelated control with the previous label from overriding that identity.
Semantic fallback and ambiguity refusal remain covered by tests. Three new
unit tests and all 17 existing M2 browser regressions passed.

Each live request received a 31,950-character context rather than the full
87,078-character observation inventory. The actual outbound token counts were
9,918, 9,922 and 9,923 including fixed instructions. Prompt caching reused
2,295 tokens on both repeats. This is measured cache reuse, not a claim that
the entire prompt is cached.

The permanent deep/crowded tests passed with both debug and release bindings.
Recorded task times were 3.821/37.818 seconds for deep/crowded in debug and
3.684/54.206 seconds in release. The crowded fixture remains slow and timing
varies with local load. These are individual software smoke samples, not
latency percentiles, a controlled performance benchmark, or evidence that
arbitrary retailer/long-running tasks succeed. The installer now selects
release builds; developer `make bindings` retains its development profile.

The logs and JSON evidence are in the same local directory:

- `live-luna-before-identity-fix.json`
- `live-luna-after-identity-fix.json`
- `live-luna-release.json` and `live-luna-release.log`
- `deep-dom-identity-fast-path.xml`
- `deep-dom-release.xml`

## Quality checks in this pass

- Extension 0.1.7: TypeScript, ESLint, Prettier, **73 Vitest tests**, production
  build passed.
- Python: final full default suite passed **660 tests**, with **30 intentional
  skips**. The combined protocol/provider-context/privacy/Luna regressions also
  passed **74 tests**. Ruff and strict Pyright passed.
- Packaged extension 0.1.7: both permanent deep/crowded scenarios passed with
  the final release binding. All five targeted pause/resume, stop, approval and
  denial control regressions passed. Three bounded live Luna smoke runs passed,
  with one actual provider call each.
- Local Markdown paths: the final check covered 92 files, including ADR-021,
  with no missing targets.
- Rust formatting and Clippy passed. The workspace test run passed the earlier
  crate/integration groups but stalled in `stress_runtime` for over 20 minutes
  without progress. It was terminated along with its owned fixture browser.
  The full Rust test gate is **incomplete**, not green.
- The final workspace run with the twelve stress cases explicitly filtered
  passed **134 tests**, with **one ignored**. All 25 M3 execution regressions
  passed. One prior M3 expectation assumed a relabeled DOM button received a
  new alias; the regression now additionally checks its original numeric ID
  and reference, updated `Ready now` label, enabled state, and successful
  action, matching the stable identity contract.

The restart test proves safe termination and reattachment. It does **not** prove
resuming a persisted run through the extension after process restart. The
current extension service exposes no such public resume flow. Existing SQLite
recovery tests cover a separate runtime path.

New test sources:

- `python/tests/extension/test_extension_reliability_e2e.py`
- `python/tests/extension/test_diagnostics.py`
- `examples/demo_site/extension-reliability.html`

## Gates still required

- Paired runtime/extension 0.1.7 acceptance on the user's installed Chrome.
- Complete the failing attached target-blank ownership scenario.
- Original 24-task re-evaluation through the extension wherever feasible.
- Resolve the stalled Rust stress gate. Final link/diff checks are tracked
  alongside the local evidence files.

No Jev calls or Laya tuning are permitted. Laya remains shadow-only. Paid Luna
regression calls start only after the deterministic infrastructure gate passes.


## October 22 revalidation before inference

The user-requested attached-backend gate ran before any new hosted inference.
The current checkout is `mango`, branch `migration/browski-v2`, with pre-existing
uncommitted source-transfer work retained. General/Fast remain managed engines;
these tests explicitly select Legacy when proving Rust/extension attachment.
No new OpenAI/Jev request, local model run, model tuning or benchmark-label
change was used.

| Gate | Observed result | Scope |
| --- | --- | --- |
| Rust generation-race regression before fix | Failed at one-second timeout | Reproduces the recursive registry-lock wait |
| Same regression after fix | Passed | One retry, second-race refusal, subsequent observation works |
| Full Rust workspace after fix | 147 passed; one manual benchmark ignored | All twelve stress cases passed in 28.58 seconds |
| Rust fmt / strict Clippy | Passed | Workspace and all targets |
| Native port-ownership regressions before fix | Two failed, six existing cases passed | Old-port callback corrupts handshake/current run |
| Full extension software checks after fix | 76 passed; types/lint/format/build passed | Built version 0.2.4 |
| Full default Python | 743 passed, 117 opt-in skips, 115.54 seconds | Rebuilt optimized binding; no live model opt-ins |
| Python formatting / strict Pyright | Passed | 219 formatted files; zero type errors |
| Python Ruff lint | Passed after two literal-wrap corrections | Exact string values preserved; migration feature edits remain uncommitted |
| Initial unchanged popup differential | Mode A passed, Mode B failed after one action | Mode C not reached; no owned supporting-tab candidate |

The initial full Rust run stalled and its verified owned test/browser processes
were terminated after inspection. It is not a passing run. The deterministic
before/after regression proves the newly repaired lock defect. A complete green
rerun is stronger than the historical non-stress subset, but does not establish
that every prior hang had the same cause.

The native port regressions replay callbacks directly at the listener boundary.
They prove state isolation after replacement, not a measured incidence rate in
Chrome. Real packaged reconnect/reload tests exercise the transport lifecycle
separately. No browser permissions or protocol capabilities were broadened.

### Original 24-case baseline, preserved

The table below reads the saved October 15 **tuned development + V3 holdout**
rows. It is historical managed-browser/model evidence, not a new run. A grader
pass can intentionally mean asking the user or waiting for confirmation.
Task IDs refer to the frozen JSONL definitions; task text, bounds and gold are
unchanged. B/C values are deliberately unmeasured for this corpus. The six-case
differential fixture suite is separate and cannot substitute for these tasks.

| Frozen case | Size | Historical managed grader | Historical runtime | New attached B/C |
| --- | --- | --- | --- | --- |
| `dev-s-03` | small | pass | `completed` | Not rerun |
| `dev-m-06` | medium | pass | `completed` | Not rerun |
| `dev-m-02` | medium | pass | `completed` | Not rerun |
| `dev-s-05` | small | pass | `completed` | Not rerun |
| `dev-s-06` | small | pass | `awaiting_user` | Not rerun |
| `dev-m-04` | medium | pass | `completed` | Not rerun |
| `dev-l-06` | large | pass | `completed` | Not rerun |
| `dev-m-01` | medium | pass | `completed` | Not rerun |
| `dev-s-04` | small | pass | `completed` | Not rerun |
| `dev-l-04` | large | pass | `pending_confirmation` | Not rerun |
| `dev-m-05` | medium | pass | `completed` | Not rerun |
| `dev-l-01` | large | pass | `completed` | Not rerun |
| `dev-m-03` | medium | pass | `completed` | Not rerun |
| `dev-l-03` | large | fail | `failed` | Not rerun |
| `dev-l-05` | large | fail | `awaiting_user` | Not rerun |
| `dev-s-02` | small | pass | `completed` | Not rerun |
| `dev-s-01` | small | pass | `completed` | Not rerun |
| `dev-l-02` | large | pass | `completed` | Not rerun |
| `v3-l-01` | large | fail | `failed` | Not rerun |
| `v3-m-01` | medium | fail | `awaiting_user` | Not rerun |
| `v3-l-03` | large | fail | `awaiting_user` | Not rerun |
| `v3-l-02` | large | fail | `awaiting_user` | Not rerun |
| `v3-l-04` | large | fail | `awaiting_user` | Not rerun |
| `v3-m-02` | medium | fail | `awaiting_user` | Not rerun |

Historical totals remain **16/18 development**, **0/6 holdout**, **16/24 combined**.
By size across those 24: small **6/6**, medium **6/8**, large **4/10**. These are
saved-corpus grades, not current extension task-success rates. The new 24-task
run remains pending: routine paid inference is disabled, the deterministic
attached popup capability still fails, and the replacement engines do not yet
control personal attached Chrome tabs. No automatic paid rerun was started.

### Completion audit still open

- Native `_blank` popup ownership must be solved within a bounded, authorized
  attachment contract. Do not adopt unrelated existing tabs or replace attached
  mode with managed mode to improve the result.
- Runtime restart currently proves cancellation/no replay and explicit new
  attachment. It does not prove durable extension run continuation.
- Legacy event correlation has run/request/browser-session/trace/step fields,
  but the complete original cross-layer identifier tuple, including tab identity
  at every Rust transition, remains unaudited rather than complete.
- Current user-installed Chrome acceptance and the new 24-task extension/model
  evaluation remain unproven. Software fixture success does not prove arbitrary
  public-site task reliability.
- Initial lint found two E501 violations in pre-existing migration edits.
  Wrapping the literals without changing their values clears the lint/format
  gate. Those feature files remain uncommitted; no lint rule was relaxed.

Reproduction uses the existing real Chromium/native-host harness and
`PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright"`, with
`BROWSKI_EXTENSION_E2E=1`, `BROWSKI_GENERAL_LIVE_DEBUG=0` and
`BROWSKI_LAYA_E2E=0`. Keep the full original corpus and difficult popup case.


### Final packaged result for this follow-up

With optimized Rust bindings and built extension **0.2.4**, the unchanged
five-module packaged group finished with **31 passed, one failed, ten explicit
opt-in skips**, in **461.01 seconds**. The sole failure is `multi_tab` in the
six-case A/B/C differential suite. The other five differential cases pass all
three modes. No failing assertion was removed or changed to xfail.

The ten skips are six CPU-Laya product cases and four spent navigation cases;
those opt-ins were intentionally disabled. The official General Agent's
navigation/read case and all four form-approval variants still ran with offline
HTTP inference, actual Chrome, Native Messaging and the packaged panel. The
provider warning in the failing popup test names the Legacy adapter `openai`,
but its provider is the fixture `ScenarioReasoner`; there was no network API call.

| Actual packaged scenario | Result | JUnit case duration |
| --- | --- | ---: |
| Full multi-step/multi-tab demo, stop before submission | Pass | 23.315 s |
| Pause/resume with verified trace | Pass | 11.748 s |
| Stop during decision | Pass | 13.673 s |
| Extension reload cancels pending action | Pass | 7.277 s |
| Runtime restart, no replay, new explicit attachment | Pass | 12.352 s |
| Nested document panel task | Pass | 10.096 s |
| Crowded nested document panel task | Pass | 57.771 s |
| Ten-action journey through A/B/C modes | Pass | 34.262 s |
| Native `_blank` differential | Fail in B after A passes | 10.235 s |

These are test-case durations with fixture/harness work, not autonomous model
latency percentiles or a broad task-success benchmark. Two pytest warnings note
that `record_property` is incompatible with the default xunit2 schema; recorded
properties are still present in the XML. No test was skipped because it failed.

Owner-only evidence is retained locally, ignored by Git, at
`debug-logs/extension-reliability-20261022/`:

- `browski-extension-differential-20261022.xml` — initial popup reproduction;
- `browski-python-20261022.xml` — complete default Python result;
- `browski-native-host-20261022.xml` — all eight listener-boundary cases;
- `browski-packaged-extension-20261022.xml` — complete 42-case packaged group.

The read-only installed-runtime check is separate: `browski doctor` finds the
binding, Chrome, native-host registration, extension build and pinned local
checkpoint, with Fast/Laya and paid inference disabled. `browski doctor
--extension` fails its authenticated runtime probe because the user's normal
bridge service is not running. This is not a passing installed-Chrome task test.
Starting/reconnecting that installed session remains a separate acceptance step.

Commits: Rust repair `1d96423`; Native Messaging repair `67504fc`.
Uncommitted source-transfer migration work was preserved (with two literal-only
lint wraps); it is not included in these repair commits. The full goal remains
active: the native-popup failure and the other open completion gates above are
not converted into a success claim.

Final repository checks: **102 tracked Markdown files, 213 local links, zero
missing paths**; `git diff --check` passes. Six unavailable historical private-log
hyperlinks were converted to explicit local-artifact references, without adding
private logs to Git. Both lint-only Python literal wraps preserve the complete
module AST, checked against their pre-wrap forms. `CODE_QUALITY.md` is unchanged.
