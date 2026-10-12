# Live BROWSKI repair smoke report — 2026-10-12

## Scope

This report records two different kinds of evidence from local fixtures:

1. The four frozen prompts from the 2026-10-09 diagnosis, rerun through the
   repaired runtime and, for the form task, the packaged extension.
2. Three new Luna tasks against local synthetic pages: a region picker, a
   staged registration form, and a multi-tab laptop shortlist.

The runs used headless Chromium, the configured Luna provider (`gpt-6-luna`),
and independently checked final browser state. They do not measure public-site
success rates. The shopping task used a local fixture, not a retailer; it did
not place an order. No signed-in user tab was used.

The frozen prompt file is
[`cases.json`](../../debug-logs/original-smoke-rerun-20261012/cases.json),
SHA-256 `53739a33eb3adb3b40178ddb706a2b0d517d127f7ebe2a512020f66a0a017459`.
Its four prompts were kept unchanged. The 2026-10-09 diagnosis at
[`live-agent-smoke-2026-10-09.md`](live-agent-smoke-2026-10-09.md) recorded
zero complete goals from four attempts at commit `ff5da36`.

## Frozen prompt reruns

| Task | Oct 9 baseline | First Oct 12 rerun | Final Oct 12 result | Independent check |
| --- | --- | --- | --- | --- |
| Click Increment exactly once | Failed; 0 actions, 1 call, 9.829 s | Completed; 1 action, 2 calls, 12.545 s | Same successful run | Counter showed one increment |
| Select Karnataka in State dropdown | Failed; 0 actions, 1 call, 4.554 s | Awaited user; 0 actions, 2 calls, 9.269 s | Completed; 1 action, 2 calls, 15.345 s | Selected option was Karnataka; page showed `Selected: ka` |
| Scroll until bottom text is visible | Failed; 0 actions, 2 calls, 14.922 s | Awaited user; 0 actions, 2 calls, 6.778 s | Completed; 2 actions, 3 calls, 17.330 s | Bottom text was inside the viewport |
| Fill name and open role details in packaged extension | Failed; 9 typing actions, 11 calls, 103.906 s; Continue click was rejected | Completed; 2 actions, 3 calls, 28.119 s | Same successful run | Name was `Smoke Tester`; role details were visible; application was not submitted |

The first Oct 12 rerun is retained in
[`original-smoke-rerun-20261012`](../../debug-logs/original-smoke-rerun-20261012/).
It passed the click and attached-form checks, but selection had no authorized
select candidate and the scroll request did not produce a usable action. The
last two managed cases were rerun with their same frozen prompts and passed;
their results are in
[`original-two-final-20261012/results.json`](../../debug-logs/original-two-final-20261012/results.json).
The attached run used the actual packaged extension (`0.1.1`) connected to
the isolated local demo site, rather than a decision-provider fixture. Its
result and independently inspected form state are retained under
[`original-smoke-rerun-20261012`](../../debug-logs/original-smoke-rerun-20261012/).

## New Luna fixture tasks

| Task | Final completed run | Raw provider calls | Rust action results | Wall time | Independent completion check |
| --- | --- | ---: | ---: | ---: | --- |
| Short region picker | `81f4e329` | 3 | 2 | 16.675 s | Visible status was Pune; semantic selected value was the AX label `Pune` |
| Medium staged registration | `3367785d` | 6 | 6 | 36.408 s | Visible saved status encoded the requested name, email, session, and opt-in |
| Long laptop shortlist | `cfdce2da` | 6 | 7 | 37.893 s | Five expected local tabs were open and the shortlist status named Northstar Studio 14 |

The 2026-10-12 reruns also exposed two checker/parser issues. In
[`final-build-all`](../../debug-logs/task-repair-20261012/final-build-all/),
the short task reached `completed` and showed the requested Pune result, but
the harness expected the HTML option's machine value `pune` while the semantic
snapshot reported the selected accessibility label `Pune`. The user prompt
and goal did not change. The expected semantic value was corrected to `Pune`,
and rerun `81f4e329` passed the independent value and visible-text checks.

The same `final-build-all` run showed all six medium actions verified and the
requested final status visible, but the task ended `awaiting_user` despite a
summary string saying it was complete. Its evidence combined two authorized
field checks with `AND`; the bounded evidence parser then supported
semicolon-separated checks only. After adding support for conjunctions whose
individual terms all match recognized evidence forms, rerun `3367785d`
completed and passed. This parser recognizes the bounded terms; it does not
evaluate arbitrary expressions.

The final long task passed on run `cfdce2da`. Earlier long attempts remain in
the artifacts: `788f0cff` stopped after four actions because Luna proposed an
action outside the candidate set; `dc4df56f` returned a structured
`milestone_plan` response that failed validation because its plan also
contained mixed action candidates, so no browser action ran; and
`33e1460b` ran 19 steps with 17 raw provider calls before ending
`awaiting_user` after repeated action-verification failures. The prior
owned-tabs run `ae8b2bc9` also completed in 65.322 seconds with 11 calls and
eight actions. These failures are retained as part of the repair history.

An earlier medium rerun (`8fb68bb5`) also completed in 34.370 seconds with
seven calls and six actions. The final conjunction check (`3367785d`) is the
latest completed medium result and used six calls and six actions.

The three final completed fixture runs together used 15 raw provider calls
and 15 Rust action results. Recorded provider-response latency totaled
77.792 seconds, with a median of 4.430 seconds (minimum 3.236, maximum 9.713).
Usage telemetry totaled 46,321 input and 3,935 output tokens. This is summed
per-call provider latency, not task wall time. Rust phase totals across these
runs were 0.357 s pre-observation, 0.167 s action execution, 6.210 s settling,
0.341 s post-observation, and 0.001 s verification, as recorded by
`browser.action_result`.

Artifacts:

- Initial short and medium attempt logs and summaries:
  [`task-repair-20261012`](../../debug-logs/task-repair-20261012/).
- Medium validated rerun, run `live-smoke-medium-preferences-8fb68bb5`:
  [`validated-rerun`](../../debug-logs/task-repair-20261012/validated-rerun/).
- First long attempt, run `live-smoke-long-shopping-tabs-788f0cff`:
  [`validated-rerun/events`](../../debug-logs/task-repair-20261012/validated-rerun/events/).
- Successful long rerun, run `live-smoke-long-shopping-tabs-ae8b2bc9`:
  [`owned-tabs-rerun`](../../debug-logs/task-repair-20261012/owned-tabs-rerun/).
- Final long run, `live-smoke-long-shopping-tabs-cfdce2da`:
  [`final-build-all/long-shopping-tabs.json`](../../debug-logs/task-repair-20261012/final-build-all/long-shopping-tabs.json).
- Short run before the semantic-label correction:
  [`final-build-all/short-picker.json`](../../debug-logs/task-repair-20261012/final-build-all/short-picker.json).
- Passing short rerun, `live-smoke-short-picker-81f4e329`:
  [`final-short-semantic-check`](../../debug-logs/task-repair-20261012/final-short-semantic-check/).
- Passing medium conjunction rerun, `live-smoke-medium-preferences-3367785d`:
  [`final-medium-conjunction-check`](../../debug-logs/task-repair-20261012/final-medium-conjunction-check/).
- The later long verification-failure and provider-unavailable runs remain in
  [`final-validated-rerun`](../../debug-logs/task-repair-20261012/final-validated-rerun/)
  and [`final-batch-rerun`](../../debug-logs/task-repair-20261012/final-batch-rerun/).
- Final snapshots are saved beside each successful run's case JSON.

The case manifests were written before their runs. Their SHA-256 checksums
are:

- Medium plus initial long selection:
  `02f85c6c82b989ddcbf511a886a6c634333440a78ece4d71bbca9e2a7746d1a3`
  ([manifest](../../debug-logs/task-repair-20261012/validated-rerun/case-manifest.json)).
- Successful long owned-tabs case:
  `e74c6aacaa5ce803b36f8fd199290612547328ad967f92cd72d43a77ce472ac9`
  ([manifest](../../debug-logs/task-repair-20261012/owned-tabs-rerun/case-manifest.json)).
- Final short semantic-value case:
  `bc2c4feaf4bef59f072708c8a8bbf959a5fab96512f28ae7e35e29a02d500898`
  ([manifest](../../debug-logs/task-repair-20261012/final-short-semantic-check/case-manifest.json)).
- Final medium conjunction case:
  `8bbca4b5066dda1bcbd2329f5e5e6fde60e0a44f39e14b6018a7b876b15f5d56`
  ([manifest](../../debug-logs/task-repair-20261012/final-medium-conjunction-check/case-manifest.json)).
- Final long case from the all-case build:
  `8a13bcc6704ab1cb3a186ef6f890e2515c5cffe9879b5e71a7c9a9ec49df455d`
  ([manifest](../../debug-logs/task-repair-20261012/final-build-all/case-manifest.json)).

## Fixture and interpretation caveats

The native-select fixture includes a deliberately hidden paragraph and an
offscreen paragraph. They were added to check that the visible-text goal does
not pass from hidden or out-of-viewport page content. The extra text is test
instrumentation, not a claim about real site markup. The medium registration
fixture also hides its contact stage after Continue and builds the final
visible status from the entered values; its independent end check therefore
validates that status instead of reading hidden form controls.

The synthetic laptop catalog uses explicit local URLs and labels, and the
shortlist is local browser state. Its successful result establishes that this
particular multi-tab fixture workflow completed. It does not establish
reliability across retailers, authentication flows, dynamic catalogs, or
purchase flows. Across the staged attempts described above, failures remain
part of the result; the eventual successes are not a universal 100% success
claim.

## Repair signals

The frozen tasks now cover click, select, scroll, and a form continuation
through the packaged extension. The new fixtures add value selection,
multi-step evidence, and opening distinct tabs before checking a local
shortlist. The earlier failures were still useful: the first selection and
scroll reruns lacked valid actions, the first medium run lacked completion
evidence, and the first long run hit a bounded-candidate mismatch. Those
outcomes show the remaining sensitivity to candidate generation and
completion evidence even though their subsequent controlled reruns passed.

No public retailer, application submission, or user-owned browser tab was part
of these runs.

## Quality gates and evidence limits

The final repository gate run completed after the harness regression was
added:

- `make test`: Rust passed; Python reported 465 passed and 16 skipped.
- `make lint`: formatter, Clippy, Ruff, and strict Pyright passed with zero
  type errors.
- Extension checks: TypeScript and 49 tests across 10 files passed; packaged
  extension `0.1.1` built without frontend source changes.
- Packaged-extension E2E with real headless Chromium: 13 passed in 117.71
  seconds; provider fixtures in that suite verify software contracts, while
  the smoke runs above provide the separate live Luna evidence.
- Markdown links in 51 files resolved locally; `git diff --check` and the
  changed-file secret-literal check passed.

The live Luna results depend on the configured model/provider response and
the local browser environment. Deterministic tests and these fixture runs do
not guarantee behavior with other providers, environments, or pages. Debug
artifacts are ignored by Git and are not copied to fresh clones; the linked
run files are available only while the local artifact directories are kept.
