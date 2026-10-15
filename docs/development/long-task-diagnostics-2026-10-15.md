# Long-task diagnostics and prompt-cache evaluation

## Scope

This continues the [frozen V1 evaluation](task-mix-evaluation-2026-10-14.md).
Development gold remains unchanged. All browser tasks use real headless
Chromium, Rust observation/execution and GPT-6 Luna. There are no Jev requests
or Laya executable decisions. These are local synthetic workflows, not evidence
of live shopping-site reliability.

## Development attempts retained

The six original long development tasks ran with an explicit extended policy:
three times their original step/call budgets, capped at 180 seconds per case.
This allows up to 24 Luna calls; it does not change the original V1 score.
Each runtime was copied with its native binding and checksums before inference.

| Frozen runtime | Complete suite | Strict long-task passes | Luna calls | Notes |
|---|---|---:|---:|---|
| V2 | Yes | 1/6 | 52 | More budget alone did not resolve the failures. |
| V3 | No | 1/3 completed cases | 53 in completed cases | Stopped after identifying stale post-action state reuse. |
| V4 | Yes | 2/6 | 66 | Fresh snapshots resolved the tab loop and ordered release workflow. |
| V5a | Yes, 18 mixed cases | 1/6 long; 12/18 overall | 105 overall | All medium cases passed; terminal-contract and omitted-work failures remained. |
| V6a | Yes, 18 mixed cases | 5/6 long; 16/18 overall | 106 overall | Draft-invariant refusal and shared action-proof reuse remained. |
| V7 | Yes, 18 mixed cases | 4/6 long; 15/18 overall | 112 overall | Draft and actual two-item pinning worked; other failures remained. |
| V8 | Yes, 18 mixed cases | 4/6 long; 16/18 overall | 125 overall | +1 check vs V7; independent V3 holdout scored 0/6. |

V3 is an interrupted diagnostic prefix, not a six-case score. Any unfinished
case requests remain in its raw debug events and are not included in its
completed-case call count. An `interruption.json` records why it stopped.

### Failure analysis

- **Stale post-action cache:** Python retained the first action's post-state
  and reused it for later progress and task-evidence checks. Rust still
  executed and reported its action verification. Later opened tabs were absent
  from Python's cached post-state, so their proofs were not recorded and Luna
  repeatedly opened the same link.
- **Missing recording intent:** “in its own tab” did not match the local
  cross-page grammar. No destination or authorized source values were created,
  so one task alternated between tabs until its call budget expired.
- **Unusable future evidence:** a plan expected `Model recorded`, while the
  real page said `Recorded Field 13: 16 GB memory, 256 GB storage.` The browser
  work was correct, but the plan could not finish. A final interpretation with
  plan fields then violated the structured response contract.
- **Premature grouped completion:** one item-specific pin status satisfied a
  milestone that represented two requested tickets. Only one ticket was pinned.
- **Approval gap:** a neutral JavaScript button could avoid the label-based
  risk classifier even when the user explicitly requested approval.

These are interface, orchestration and policy findings. They do not establish
that the model alone was responsible.

## Fixes under evaluation

1. Fresh pre-action observations invalidate the preceding post-action cache.
   Every execution explicitly observes and saves its own post-state.
2. Source-bound per-link proofs retain ref, generation, fingerprint and the
   one new owned tab. Proved links leave the candidate set; requested-link
   clicks obey the same eight-tab bound as explicit new-tab actions.
3. Task-scoped tab labels distinguish the source and inspected destinations.
   Comparison memory remains untrusted and cannot authorize field values.
4. Explicit own-tab wording can authorize cross-page recording. Copied values
   still come from current visible source references and unique destination
   bindings, not model text.
5. Verified initialized plans can revise evidence to the actual current page
   state. Initial static-label rejection remains. Prompts request valid
   milestone plans and separate evidence for explicitly enumerated effects.
6. One counted response-format repair is permitted within the run budget.
   Request, authentication, timeout and local context-size failures do not
   use that repair path.
7. Recognized explicit approval requests conservatively gate clicks, keypresses,
   dialogs and tab closure even with neutral labels. This can request consent
   before the final operation. Separate real-Chromium tests cover approval
   and denial with both neutral and consequential labels.
8. `task_complete` is an explicit proposal with the initialized identifiers and
   proof. It cannot replace proof, reset completed steps, or authorize actions.
   Unusable proof must first be corrected through an explicit plan revision.
   Rejected completion proposals preserve the task and continue within call
   and stagnation limits. Static text substitution and subsequent recovery
   have real-browser regression coverage.
9. A standalone explicit search request can use a local type-then-Search plan
   only when its field and button are uniquely observed. Compound queries,
   additional constraints and ambiguous controls still require planning.
10. A verified action witness can advance one event-dependent milestone. It
    cannot prove two separate item operations merely because both item labels
    are visible near a shared detail-panel button. A new verified action
    creates a new witness. Field, selection, checkbox and owned-link state
    checks remain reusable. Explicit replans preserve completed steps only
    when both their identifiers and evidence are unchanged.
11. A failed or unverified action clears the preceding action's
    `verification_success` progress signal. The runtime still refuses
    completion without the required verification and evidence. This prevents
    a stale success flag from inviting repeated completion proposals after a
    no-op or failed action; it does not convert that action into success.

See [ADR-019](../decisions/ADR-019-grounded-commands-and-canonical-candidates.md).

## Prompt-cache measurements

The [two-call probe](../architecture/prompt-caching.md) confirmed a warm read of
2,112 of 2,466 input tokens. V4's 66 requests reported 257,559 input tokens,
139,392 cached input tokens, zero cache-write tokens, and 10,861 output tokens.
Every request reported these counters. This warm run reused a prefix created
earlier; it is not a cold-start estimate.

These are provider usage counts, not billed currency or an aggregate savings
claim. Cache writes and reads have different pricing semantics. Failed and
interrupted attempts also consume requests and must remain in the evidence.
The static prompt changes between runtime versions, so cache usage must be
reported for each version rather than assumed universal.

## Local artifacts

All raw requests, public responses, browser diagnostics and runtime copies stay
in ignored, owner-only local storage under `debug-logs/task-mix-20261015/`:

- V2: `optimized-20261015T052004Z-c417302d/`.
- Interrupted V3: `optimized-20261015T060417Z-aec1bd1e/`.
- V4: `optimized-20261015T061526Z-e7103a25/`.
- V5a: `optimized-20261015T062809Z-431c1570/`.
- V6a: `optimized-20261015T172940Z-fcd73623/`.
- V7: `optimized-20261015T174546Z-2285c764/`.
- V8 development: `optimized-20261015T175825Z-d63004a3/`.
- V8 independent V3 holdout: `optimized-20261015T180838Z-972dd430/`.
- Frozen packages: `frozen-runtime-v2/`, `frozen-runtime-v3/`,
  `frozen-runtime-v4/`, `frozen-runtime-v8/`.
- Cache probes: `cache-probe/`, `cache-probe-follow-up/`.
- Software validation and runner logs: `validation/`.

V5 was frozen but not used for inference after a formatting issue was found.
The format-clean V5a snapshot is retained separately. No frozen source copy or
prior result was overwritten.

V5a was interrupted after 17 completed cases and resumed for the final case
with the same frozen source, harness identity, policy and order. The resume
records its new timestamp and local fixture origin. Unfinished earlier
provider events remain in the raw logs. Its complete strict result is 12/18:
5/6 short, 6/6 medium and 1/6 long. Three long cases met the browser-state gold
but did not reach runtime completion. The other two long failures omitted
requested checklist or pinning work; they are not merely formatting problems.

The unused V6 copy was retained after defensive obsolete-plan-proof cleanup
required a new V6a freeze. V6a's manifest checksum is
`cd36721dd5997061410de1906419ff901884fa1a6ac51006de0bc68e51aa5610`.
It passed 16/18 cases: 6/6 short, 5/6 medium and 5/6 long. Its median task
latency was 16.9 seconds; p95 and p99 were 97.1 seconds. The three-product
comparison task passed but needed 19 calls and 97.1 seconds.

V6a's draft failure was caused by rejecting a requested unchanged negative
state while the form's required fields were still empty. Its pinning failure
was a runtime false completion: two item milestones reused one verified click
of a shared pin button, with both static item labels already visible. These
findings motivated explicit regressions and a separately frozen V7 runtime;
V6a's original score and raw outputs remain unchanged.

V6a reported 431,527 input tokens, 240,975 cached input tokens, 2,295 cache-write
tokens and 20,844 output tokens across 106 requests. All usage fields were
reported. One request created the prefix and 105 read it. Cached tokens were
55.8% of reported input. This is not a billed-cost estimate.

The independent V3
holdout was authored and committed before these development results. Its cases
and expectations are not used for tuning. Different dataset sizes and budget
policies must be reported separately; they are not a paired accuracy delta.

## V7 findings and final freeze

V7 passed 15/18 strict checks: 6/6 short, 5/6 medium and 4/6 long. Its median
task latency was 16.4 seconds; p95 and p99 were 68.6 seconds. The draft task
passed. The two-ticket task genuinely pinned both requested tickets and chose
the requested queue; its only failed gold check was a nonempty search query.
The task text does not explicitly require using that query route. The primary
score remains failed, pending a separate qualitative review of the benchmark.
No gold label or recorded result is changed.

The other V7 failures were operational: a schedule was saved but the model
repeated Save, received failed verification and then repeatedly proposed
completion; another long workflow did not finish its release checklist. These
are not treated as successful tasks. Clearing the stale verification progress
flag is included in V8 and covered by a real-browser success-then-no-op test.

V8 is the final source freeze for both the last development rerun and the
independent holdout. The runtime is not tuned after reading holdout outcomes.
All counts include intended clarification and pre-action confirmation outcomes
when those are the frozen expected behavior. They are task-check pass counts,
not a claim that every case executes through final submission.

## Environment

- Intel Core i5-8350U, four cores / eight logical CPUs, approximately 15.4 GiB RAM.
- Fedora kernel `7.2.7-200.fc44.x86_64`, x86_64.
- Python 3.12.13; OpenAI SDK 2.54.0; Pydantic 2.13.5; LangGraph 1.2.12.
- Managed Google Chrome 154.0.8037.57; Playwright 1.63.0 for extension acceptance.
- Active model identifier: `gpt-6-luna`; ordinary requests use low effort.
  High effort remains gated by `ComplexityGate` and is reported when used.
- No Jev requests, executable Laya decisions, weight changes or fine-tuning.

These are small local fixture runs on a desktop, not controlled public-site
speed or cost studies. Provider sampling is not asserted deterministic. The
development iterations change multiple interfaces and policies, so their
differences are descriptive rather than isolated causal estimates.

## V8 final evaluation and readiness

Both final suites used the same frozen runtime manifest
`1c6f9abafad135f3678fb3ec2215ac801fee36a1da637e1577b7e06d9feca95f` from
Git base `323c1edcc0d1395551bd8ba90c1d514572bcb05d`. The development corpus
checksum is `f21ff579f176cd99949b07d4dda5e022ac59b10732e58ede716b52163e071a07`.
The frozen source and manifest were not changed after the independent holdout
was read. No further prompt or model tuning, nor paid model calls, followed the
holdout.
The aggregate records are in
[`comparison.json`](../../benchmarks/task_mix/results/2026-10-15/comparison.json)
and [`comparison.csv`](../../benchmarks/task_mix/results/2026-10-15/comparison.csv);
the separate blind judgments are in
[`blind judgments`](../../benchmarks/task_mix/results/2026-10-15/blackbox-judgments.jsonl).

| Run | Strict (short / medium / long) | Calls | Task p50 / p95 (ms) | Input / cached / output tokens |
|---|---:|---:|---:|---:|
| V5a development | 12/18 (5/6 / 6/6 / 1/6) | 105 | 22,825.91 / 85,451.03 | 417,538 / 223,992 / 20,410 |
| V8 development | 16/18 (6/6 / 6/6 / 4/6) | 125 | 17,502.61 / 131,324.39 | 519,121 / 286,875 / 28,349 |
| V8 independent V3 holdout | 0/6 (— / 0/2 / 0/4) | 41 | 18,270.5 / 129,702.75 | 149,360 / 94,095 / 11,574 |

The holdout has been used. Keep its cases and expected outcomes sealed from
future tuning; do not reuse it as development gold. A later evaluation needs a
new independently authored holdout.

The V8 development rerun scored **16/18** by the frozen browser-state task
checks: 6/6 short, 6/6 medium and 4/6 long. It used the same three-times
extended development budget as V5a, with up to 30 Luna calls and 120 steps per
case. The run made 125 Luna calls, with 519,121 input tokens (286,875 cached)
and 28,349 output tokens. Task latency was p50 17,502.61 ms and p95/p99
131,324.39 ms. Luna-call latency was p50 3,144.84 ms, p95 6,629.46 ms and p99
9,418.49 ms. No provider errors were recorded. The remaining failures were:

- `dev-l-03`: the release checklist did not reach all four required steps and
  the run failed at its call limit.
- `dev-l-05`: the queue and requested ticket pins were not completed, and the
  required search query remained empty when the run asked the user for input.

From paired runtime `ActionStarted` to `ActionCompleted` events, all 92 V8
development action intervals matched: p50 650 ms, p95 995 ms and p99 1,376 ms.
All 29 holdout action intervals matched: p50 522 ms, p95 628 ms and p99 629 ms.
These intervals include settling and verification; they are not raw CDP click
latency. Luna call medians were several seconds, so the action figures do not
mean a whole task or decision happens in under a second.

The fresh, independently authored V3 holdout scored **0/6** on the same V8
runtime: 0/2 medium and 0/4 long. It used the original per-case budget with a
180-second cap, making 41 Luna calls and recording no provider errors. Five
cases stopped awaiting user input with required task effects incomplete; the
remaining long case exhausted its call budget. Task latency was p50 18,270.5
ms, p95/p99 129,702.75 ms. Luna-call latency was p50 4,239.03 ms, p95
6,988.71 ms and p99 12,119.64 ms. The failures show gaps in literal and field
grounding, native date entry, option selection, source-to-field recording and
candidate coverage. When a required control is not represented, safe refusal
can leave the task incomplete; the refusal is a protective behavior, while
the missing coverage still means the requested outcome was not achieved. The
16/18 development score therefore
did not generalize to this small independent holdout. The result is consistent
with overfitting to the development task mix; it does not estimate performance
on arbitrary public websites.

An independent blind review used 24 anonymized outcome packets from those two
V8 runs and judged 16 `CORRECT`, 8 `WRONG`. This is a qualitative review of task
effects, separate from the frozen score. The judgment file's SHA-256 remains
`54b94ac8ea8b8b3334339f6d64f75244fc3b845f58e71cfbb458edc0811b94ad`. The
review ran in a fresh fork without task-authoring context; that isolation is
not a separate operating-system permission sandbox. The evaluator was from
the same model family, so the judgment is useful qualitative review rather
than independent ground truth. No benchmark labels, expectations or judgments
were changed.

Across the V8 development and holdout runs, the agent made 166 Luna calls,
using 668,481 input tokens, of which 380,970 were cached, and 39,923 output
tokens. This is about 57% cached input by provider-reported token count. It is
not a billed-USD estimate and does not support a claim that total cost fell.
Across the 12 development cases passed by both V5a and V8, Luna calls rose
from 47 to 49, while median task latency fell from 19.48 to 17.48 seconds.
This shared subset also does not establish a call reduction.
The runs used no executable Laya decisions, no Jev requests and no weight
changes. Laya remained shadow-only and Jev remained disabled.

V8 is not reliable for arbitrary long-running browser tasks and is not ready
for a general long-task reliability claim. In particular, the final
development run still failed `dev-l-03` and `dev-l-05`; earlier V7 pinning
results must not be attributed to V8. Readiness therefore has separate scopes:

| Area | Current assessment |
|---|---|
| Product | Local UI and fixture workflows exist; public-site and general task readiness are unproven. |
| Software | The required local gates passed as recorded below; they do not establish model task reliability. |
| Security | Local controls and a threat model exist; independent security assessment, screenshot redaction and complete PII detection remain outstanding. |
| Agent | Not ready for arbitrary long tasks: development 16/18; fresh holdout 0/6. |
| Benchmark | Small local synthetic evaluation complete; spent holdout cannot be tuning gold; broader evaluation remains. |

Passing software gates would not change the 0/6 holdout result.

## Final software validation

| Gate | Result |
|---|---|
| Rust workspace tests, serial execution | 133 passed; one optional test ignored. No Rust source changed afterward. |
| Rust formatting and Clippy | Passed, including `--all-targets -- -D warnings`. |
| Python regression suite | 621 passed, 16 opt-in tests skipped; 95.77 seconds. |
| Ruff check / format and strict Pyright | Passed; zero type errors or warnings. |
| Benchmark and release-tool tests | 41 passed. |
| Extension typecheck, ESLint and Prettier | Passed for version 0.1.3. |
| Extension Vitest / production build | 49 passed; unpacked MV3 build succeeded. |
| Real packaged-Chromium extension E2E | 13 passed; 101.10 seconds. |
| Relative Markdown file paths | 85 documents checked, zero missing file targets. |
| Git whitespace validation | Passed. |

The Python suite's skips consist of the 13 extension tests run separately,
plus optional live Laya, Jev and OpenAI tests. No further paid provider calls
were made after the held-out evaluation. The earlier full extension run had
12 passes and one failure: its scripted demo parsed an obsolete owned-tab
description, causing `StopIteration` to surface as a fixture `RuntimeError`.
The fixture now selects the current bounded candidate ID and preserves its
reference-transfer evidence. Its completion assertions were not relaxed.
The corrected isolated demo and full extension suite passed. This fixture-only
correction did not change the frozen production runtime or model results.

Logs remain under `debug-logs/task-mix-20261015/validation/`, including
`final-rust-serial.log`, `final-lint-v8.log`, `final-python-v8.log`,
`final-harness-v8.log`, `extension-v013-final.log`,
`extension-e2e-v8-final.log` (the initial failure),
`extension-e2e-v8-corrected.log` and `markdown-links-v8.log`.

## Local service handoff

At the final local check on 2026-10-16 (Asia/Kolkata), the CPU Laya server
returned HTTP 200 at `http://127.0.0.1:8001/health`. The extension backend
reported listening at `/run/user/1000/browski/bridge.sock`.
`browski doctor`, run with the existing local environment loaded, confirmed
Python, Rust bindings, Chromium, SQLite writes, key presence, the built
extension, the Native Messaging host and Laya health. Doctor did not call
OpenAI. Its runtime-policy warning describes the intended Luna-active,
Laya-shadow-only, Jev-disabled configuration.

This establishes local prerequisites and a listening backend, not a connection
to the user's Chrome panel. Reload extension version 0.1.3, reopen the panel,
connect the runtime host and explicitly attach the desired tab. The unpacked
build is `extension/.output/chrome-mv3`; use the full absolute path with
**Ctrl+L** in the Chrome folder chooser because `.output` is hidden.
See [extension setup](../user/extension.md).
