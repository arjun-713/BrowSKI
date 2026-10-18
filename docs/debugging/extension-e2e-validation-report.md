# Extension reliability validation

Status: in progress. This is an evidence ledger, not a completion claim.

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
