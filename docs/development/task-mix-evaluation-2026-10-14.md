# Mixed browser-task evaluation: frozen V1

## Scope and verdict

These are real GPT-6 Luna decisions executed through BROWSKI's Rust browser
core in headless Chromium against deterministic local pages. This is a
controlled development experiment, not a public-site reliability claim.

**The frozen V1 runtime is not reliable for long tasks.** Ordinary short
interactions improved substantially, but every long case failed its complete
gold check. Two local reservation cases also revealed a confirmation-policy
defect. Later software fixes must not be represented as part of these results.

## Protocol

- Corpus frozen in commit `7f18e6c`, before any model-backed task run.
- Seed: `20261012`; task order in
  [frozen-order.json](../../benchmarks/task_mix/frozen-order.json).
- Development: 18 tasks, six each small, medium and large.
- Held out: nine tasks, three each small, medium and large.
- Small tasks target 1–2 operations, medium 3–5, large 6–10.
- Fresh managed Chromium and agent state per case. Pages make no external
  shopping, purchase, registration or reservation request.
- Deterministic evaluator checks field values, selections, checked state,
  current page text, owned tabs, runtime completion and confirmation status.
  Model completion claims do not replace these checks.
- Original case step/call/time caps were preserved. Long cases had at most
  eight Luna calls. Planning and recovery consume this budget too.
- The final development run was interrupted after 11 cases. It resumed only
  the unfinished seven, using identical runtime hashes and case order. The
  new fixture origin is recorded in `resume-manifest.jsonl`.
- Held-out tasks ran once, after the runtime freeze. No V1 labels were
  changed after observing answers. Later interface work uses development
  failures, not held-out outcomes, for tuning.
- No Jev requests, Laya weight changes or Laya executable decisions.

Development checksum:
`f21ff579f176cd99949b07d4dda5e022ac59b10732e58ede716b52163e071a07`.

Held-out checksum:
`ecd8e43f287a1170c65bd1405b24300a69c419ab5109a91a3b158e8d62364aba`.

The [runtime manifest](../../benchmarks/task_mix/tuned-runtime-manifest.json)
records 99 package/native-file hashes. Its file SHA-256 is
`0933bac1b3a53483ceae34c18ececb6b999b0150e1cddd3d6d37bf2b2b145844`.
The original frozen source copy was temporary; interruptions removed it.
The manifest and raw results survive. Future runs should retain their frozen
source package in the local artifact directory, not only under `/tmp`.

## Results

| Metric | Baseline development | Frozen V1 development | Held-out V1 |
|---|---:|---:|---:|
| Complete gold pass | 3/18 (16.7%) | 11/18 (61.1%) | 4/9 (44.4%) |
| Small | 2/6 | 6/6 | 3/3 |
| Medium | 1/6 | 5/6 | 1/3 |
| Large | 0/6 | 0/6 | 0/3 |
| Logical Luna calls | 52 | 78 | 40 |
| Laya calls / accepted actions | 0 / 0 | 0 / 0 | 0 / 0 |
| Task latency p50 | 11.35 s | 17.81 s | 20.38 s |
| Task latency p95 / p99 | 43.95 s | 44.98 s | 42.19 s |
| Luna request latency p50 | 4.61 s | 3.37 s | 2.89 s |
| Input tokens | 150,329 | 286,811 | 145,054 |
| Output tokens | 15,027 | 14,199 | 6,936 |

Percentiles use nearest rank. With 18 or nine cases, p95 and p99 equal the
maximum sample and are weak tail estimates. Task timings include observation,
model decisions, execution and verification; browser startup is separate.

There is **no aggregate call or cost saving**. The new runtime performed more
work on cases that previously failed early. Among the three cases both
variants passed, calls fell only from eight to seven, and median task latency
fell from 7.90 to 4.45 seconds. This small shared subset cannot establish a
general cost reduction. Input/output counts are provider reported; this run
did not record cache-read or cache-write token details or billed dollar cost.

Small development cases used nine total Luna calls instead of 13. Several
complete, explicitly grounded tasks used one call by avoiding a separate
planning request. This does not justify forcing every task into one call.

## Interface changes measured in V1

1. Bind explicit user literals and uniquely observed native options before
   constructing candidates. Missing or ambiguous values still fail closed.
2. Select canonical candidate IDs instead of asking Luna to reconstruct
   private values, text casing, targets or scroll distances.
3. Create local plans for complete short commands and preserve bounded,
   separately authorized and verified action batches.
4. Use native option ownership and bounded row context to distinguish
   repeated controls.
5. Reject completion evidence based on button labels, unchanged checklist
   text and negated status phrases.
6. Keep cross-page source facts separate from untrusted historical notes.
   Only locally read, explicitly requested evidence can authorize field values.
7. Reuse the owned SDK connection pool, close it at run end, and disable
   hidden SDK retries so latency and logical calls are easier to audit.

These are generic runtime rules. There are no production branches keyed to
the benchmark case IDs, local fixture routes or product names.

## Failure analysis

| Family | Evidence | Remaining problem |
|---|---|---|
| Multi-tab research | `dev-l-01`, `dev-l-06` | Repeated visits consume the call budget before source comparison and recording finish. |
| Compound field constraints | `dev-l-03` | One time candidate exists while the requested day/end-time candidates are missing. |
| Repeated result rows | `dev-l-05` | One requested ticket is pinned; another is omitted and the runtime reports completion too soon. |
| Multi-stage completion | `dev-m-03`, `dev-l-02` | Requested form values can be present while the runtime unnecessarily waits for the user or returns an invalid provider decision. |
| Confirmation | `dev-l-04` | A non-submit button labeled “Reserve this seat” is treated as an ordinary click. |

The eight-call limit is a confound for 6–10-action tasks requiring planning,
tab activation, inspection and recovery. A separately recorded extended-budget
run is appropriate; changing that budget does not improve the original V1
score and must be reported as a different execution policy.

The held-out pass rate is lower than the development pass rate. Improvements
transfer to short tasks, but generalization to compound forms and long tasks
is not established. Do not describe development gains as universal reliability.

### Reservation safety defect

The old risk policy matched `reserve seat` but missed `Reserve this seat`.
The development reservation case and the held-out reservation case changed
the local page to “Reservation submitted” before approval. No external
transaction occurred, but these are unsafe agent behaviors.

The fixture collector's `submitted` boolean only tracks HTML form-submit
events. This button uses a click handler, so that boolean incorrectly remains
false. The independent visible-text and confirmation checks still fail the
case. Inspect the actual page evidence; do not interpret the boolean as proof
that no consequential action occurred.

The subsequent risk fix treats `reserve` and `book` control tokens as
consequential. Separate real-Chromium regressions verify that the button stays
unclicked before approval and after denial, then executes after approval.
These software regressions are not a retrospective change to V1's score.

## Independent qualitative review

A fresh GPT-6 Luna high subagent received anonymized packets through neutral
`set-a` / `set-b` paths. It saw tasks, expected state, independent check booleans,
observed state, candidate descriptions and sanitized public decisions. It did
not receive repository history, aggregate scores, implementation details or
the desired outcome. It did not use the model under test's hidden reasoning.

| Set | CORRECT | ACCEPTABLE | WRONG | UNSAFE | AMBIGUOUS_BENCHMARK |
|---|---:|---:|---:|---:|---:|
| Development | 13 | 1 | 3 | 1 | 0 |
| Held out | 5 | 1 | 1 | 1 | 1 |

The reviewer considers some browser states sufficient for the natural task
even when runtime completion or an exact query check fails. Its labels are
secondary and do not replace the strict 11/18 and 4/9 gold results. Its
reservation finding was checked against the raw browser-state evidence.
Judgment files were copied byte-for-byte and checked for complete packet IDs.

## Laya evidence

The separate [Laya probe](../../benchmarks/task_mix/laya_probe_report_20261012_v2.md)
used CPU checkpoint `7b928d828b7b0e022f929d9bd2e44165aa270148`:

- Broad candidates: 20/24 canonical answers correct; all four unsupported
  cases selected action instead of escalation; order consistency 58.3%.
- One locally authorized command plus escalation: 20/20 eligible cases
  correct; order consistency 100%; four unsupported cases skipped in code.

This is not proof of safe general Laya execution. The scoped result depends
on local code establishing the only authorized operation. No production
confidence or margin threshold is recommended. The experimental routing
configuration remains disabled; production stays Luna active, Laya shadow.

## Browser latency

The separate, model-free 40-sample Chromium checkbox study on 2026-10-14
reported physical action dispatch p50/p95/p99 **11/25/35 ms**, observation
**13/36/38 ms**, and complete action/settle/verify **445/502/518 ms**. The
settle window accounts for about 405 ms at p50. These measurements describe
one local checkbox, not arbitrary pages or agent task duration.

## Artifacts

- [Comparison JSON](../../benchmarks/task_mix/results/2026-10-14/comparison.json)
  and [case CSV](../../benchmarks/task_mix/results/2026-10-14/comparison.csv).
- Local raw baseline:
  `debug-logs/task-mix-20261012/baseline-20261012T133943Z-52d3e696/`.
- Local raw final development:
  `debug-logs/task-mix-20261012/optimized-20261012T165848Z-c2c68b12/`.
- Local raw held out:
  `debug-logs/task-mix-20261012/optimized-20261014T164100Z-88f67f24/`.
- Each run retains manifest, results JSONL, provider request/response JSONL,
  safe per-run debug events, summary JSON/CSV and independent judgments.
- Earlier complete tuning attempts and interrupted partial runs remain in
  the same local artifact tree. One intermediate attempt had transport
  timeouts; it is not the final result.
- Validation history: `debug-logs/task-mix-20261012/validation/software-gates.log`.

Raw debug artifacts remain local and ignored by Git. Do not commit real user
prompts, private form values or provider payloads. Only the synthetic corpus,
safe summaries and source-level experiment tools belong in the repository.
