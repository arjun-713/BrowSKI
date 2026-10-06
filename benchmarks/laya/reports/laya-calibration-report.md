# Laya System-One Evaluation

**Evaluation date:** 2026-10-06  
**Verdict:** `NEEDS_MORE_CALIBRATION`  
**Execution policy:** no Laya decision family is enabled for executable fast-path actions; an unconfigured acceptance threshold continues to escalate.

## Environment

| Item | Observed value |
|---|---|
| Host OS | Fedora 44, Linux 7.2.7, x86_64 |
| CPU | Intel Core i5-8350U, 4 cores / 8 logical CPUs |
| RAM | 16,489,238,528 bytes (15.36 GiB) |
| Python | 3.12.13 |
| Laya package | 0.3.28 |
| Checkpoint / repo | `convaiinnovations/laya`, English revision `7b928d828b7b0e022f929d9bd2e44165aa270148` |
| Model | `laya-rl-agent`; routing model `english` |
| Device | CPU, 4 Laya threads, no CPU fallback |
| Endpoint | `http://127.0.0.1:8000` |
| Cold process startup | 22.70 s, measured by the service wrapper with model files already cached locally |

`GET /health` returned 200 and reported the English checkpoint loaded on CPU.
The actual `/v1/systemone` Choice, Score, and Noul requests all returned 200.
Their raw request/response bodies and headers are in
`../phase_a/probes.jsonl`. The observed response envelope is `model`,
`answers`, `usage`, and `routing`; each answer has a type-specific value and
probability data, plus `confidence`, `answer_confidence`, and
`action.act_probability`. Usage reported input, output, and state token counts.
Choice returns a candidate ID and candidate probabilities; Score returns a
continuous score, rubric legend, and label probabilities; Noul returns P(yes).

The service emitted this warning at startup: the English checkpoint's
`choice:11+` temperature was outside its supported range and was clamped from
`0.10058280825614929` to `0.5`; confidence for those affected entries is
uncalibrated. No confidence field was trusted without empirical measurement.

### Runtime and machine load

| Run | Laya RSS during run | Laya CPU (machine share) | System CPU | RAM available |
|---|---:|---:|---:|---:|
| Baseline V1 | 2.24–3.60 GiB | mean 36.7%, p95 48.3% | mean 95.7%, p95 100% | min 1.49 GiB, mean 3.70 GiB |
| Tuned V1 | 2.55–2.66 GiB | mean 47.6%, p95 48.6% | mean 83.2%, p95 93.7% | min 4.51 GiB, mean 5.29 GiB |
| Tuned V2 | 2.66 GiB | mean 46.2%, p95 49.2% | mean 74.8%, p95 99.6% | min 4.13 GiB, mean 5.41 GiB |

Laya used about four of the machine's eight logical CPUs. Other system activity
was substantial, especially during baseline, so the lower tuned latency cannot
be attributed to prompt changes alone. No other local model was started for
this experiment. Resource samples and the server log are preserved in
`../results/runtime/`.

## Benchmark protocol and reproducibility

V1 has 80 frozen cases: 15 next-action, 10 prerequisite/order, 8
distractor/no-op, 8 ambiguity/escalation, 8 recovery, 8 progress, 8 semantic
verification, 7 task completion, and 8 multi-constraint. It contains 49
Choice, 11 Score, and 20 Noul cases. Twenty Choice cases each received three
fixed candidate-order permutations. V1 SHA-256:
`d585b64c02132d127bf7915f7e0f650a7e9a282ea201fa41c62e7de959343fbb`.

V2 is a separate frozen holdout of 50 new cases: 32 Choice, 7 Score, and 11
Noul; 12 Choice cases received three permutations. V2 SHA-256:
`6b817a207f057651a47dc363911706a9d477d8f362e87b89c0dd9d21074610cd`.
The manifest was committed before V2 inference. No V2 result was used to tune
the interface or thresholds.

Each V1 case received three canonical repeats. Each V2 case received three
canonical repeats. Canonical responses were deterministic in all runs. The
20 V1 and 12 V2 position probes added 60 and 36 requests, respectively. Every
request and response is preserved; evaluator-only expected answers, acceptable
answers, rationale, correctness, and difficulty are written only in the
separate scored JSONL. They were never sent to Laya.

## Baseline

### Accuracy

The primary V1 denominator is 240 canonical calls; position permutations are
reported separately. Overall accuracy is 153/240 (63.75%). Since the three
output types have different semantics, the per-type results are more useful.

| Type | Correct / calls | Accuracy | Calibration / quality |
|---|---:|---:|---|
| Choice | 120 / 147 | 81.63% | answer-confidence ECE 0.280; multiclass Brier 0.359; mean top-1/top-2 margin 0.282 |
| Score | 12 / 33 | 36.36% | score MAE 0.821; answer-confidence ECE 0.142; Brier 0.627 |
| Noul | 21 / 60 | 35.00% | P(yes) ECE 0.326; binary Brier 0.322 |

Raw `confidence` ECE was 0.704 for Choice, 0.325 for Score, and 0.326 for
Noul. These are different confidence meanings and are not combined.

### Category accuracy

| Family | Correct / calls | Accuracy |
|---|---:|---:|
| Next action | 39 / 45 | 86.67% |
| Prerequisite/order | 21 / 30 | 70.00% |
| Distractor/no-op | 15 / 24 | 62.50% |
| Ambiguity/escalation | 15 / 24 | 62.50% |
| Recovery classification | 18 / 24 | 75.00% |
| Progress judgment | 3 / 24 | 12.50% |
| Semantic verification | 9 / 24 | 37.50% |
| Task completion | 15 / 21 | 71.43% |
| Multi-constraint | 18 / 24 | 75.00% |

The difficulty slice was 33/39 (84.62%) for easy calls; the medium/hard cases
were weaker. There are only 7–15 independent scenarios per family: repeats
check determinism but do not increase independent case count. Full breakdowns
by difficulty, confidence and answer-confidence bucket, margin, state-token
length, candidate count/order, and question type are in
`../results/baseline/baseline.analysis.json`.

### Confidence and simulated routing

Choice answer-confidence buckets were: 0/6 correct at 0.3–0.4, 15/21 at
0.4–0.5, 51/60 at 0.5–0.6, 45/51 at 0.6–0.7, and 9/9 at 0.7–0.8. The
apparently perfect final populated bucket is only nine calls and does not
validate a threshold. Noul calibration bins and all Score confidence bins are
in the machine-readable analysis.

| Choice rule | Coverage | Accuracy when executed | Wrong actions executed | Escalations |
|---|---:|---:|---:|---:|
| answer-confidence ≥ 0.50 | 71.43% | 85.71% | 15 | 42 |
| ≥ 0.50 and margin ≥ 0.10 | 67.35% | 90.91% | 9 | 48 |
| ≥ 0.50 and margin ≥ 0.20 | 61.22% | 90.00% | 9 | 57 |
| answer-confidence ≥ 0.60 | 34.69% | 88.24% | 6 | 96 |
| answer-confidence ≥ 0.70 | 4.08% | 100% | 0 | 141 |

The 0.70 rule accepted only six calls. Eight gold escalation scenarios
generated 24 canonical calls; 15 were explicitly escalated and 9 selected an
action. Progress and semantic-verification performance are too weak for those
decisions to be used directly.

### Position sensitivity

Across 60 V1 permutations, accuracy was 20/60 (33.33%) and semantic-answer
consistency was 35% across the 20 scenarios. Laya selected the candidate in
position 1 thirty-three times, position 2 seventeen times, and position 3 ten
times. This is material order bias.

### Baseline blind review

A fresh isolated reviewer saw one canonical sample per case, without gold
labels or aggregate score. Its 80 judgments were 50 CORRECT, 4 ACCEPTABLE,
22 WRONG, and 4 UNSAFE. The reviewer identified unsupported completion claims,
missed visible constraints, skipped prerequisites, and unsafe guesses on
ambiguous bookings/deletions or retries with unknown outcomes. Its judgments
are secondary qualitative evidence; deterministic gold remains primary. The
file is preserved unchanged at
`../results/baseline/blackbox_judgments.jsonl`.

## Interface change evaluated

The baseline Choice interface mirrored the production selector: full element
list (including noise), task and subgoal, candidates, and a short instruction.
The tuned benchmark-only variant reduced state to task, subgoal, explicit
constraints, relevant elements, recent action, recent outcome, and relevant
delta. It retained complete semantic candidate descriptions and added concise
instructions to choose one immediate action, respect prerequisites, avoid
inventing/combining actions, and escalate when evidence is missing or unsafe.
Score and Noul stayed typed with their exact proposal/evidence question and
rubric/yes-no semantics. The evaluation changed several Choice interface
elements together, so it does not isolate the causal contribution of any one
prompt field.

## Tuned V1

Tuned V1 produced 147/240 correct (61.25%), down from 63.75% baseline. By
question type: Choice 108/147 (73.47%), Score 12/33 (36.36%), Noul 27/60
(45.00%). Progress remained 3/24 (12.50%), semantic verification remained
9/24 (37.50%), and ambiguity/escalation fell to 12/24 (50.00%). Completion
rose to 18/21 (85.71%) and multi-constraint rose to 24/24 (100%), but these
small gains do not offset the broader Choice and recovery regressions.

Choice answer-confidence ECE improved from 0.280 to 0.223, while Choice Brier
worsened from 0.359 to 0.452. Score Brier was essentially unchanged (0.627 to
0.629), and Noul P(yes) ECE changed from 0.326 to 0.334 while Brier improved
from 0.322 to 0.278. Calibration changes are mixed and family-specific.

### Baseline versus tuned V1

| Metric | Baseline | Tuned V1 | Delta |
|---|---:|---:|---:|
| Raw canonical accuracy | 63.75% | 61.25% | −2.50 pp |
| Choice accuracy | 81.63% | 73.47% | −8.16 pp |
| Score accuracy | 36.36% | 36.36% | 0 pp |
| Noul accuracy | 35.00% | 45.00% | +10.00 pp |
| Executed-choice accuracy at ≥0.50 confidence and ≥0.10 margin | 90.91% | 78.26% | −12.65 pp |
| Choice execution coverage at same rule | 67.35% | 46.94% | −20.41 pp |
| Wrong actions at same rule | 9 / 99 | 15 / 69 | +6 wrong |
| Position consistency | 35.00% | 40.00% | +5.00 pp |
| Position-permutation accuracy | 33.33% | 41.67% | +8.34 pp |
| Latency p50 | 6,221 ms | 3,961 ms | −36.3%* |
| Latency p95 | 11,614 ms | 5,203 ms | −55.2%* |
| Latency p99 | 16,166 ms | 6,462 ms | −60.0%* |
| Mean reported state tokens / canonical call | 252.8 | 236.2 | −6.6% |
| Choice answer-confidence ECE | 0.280 | 0.223 | −0.057 |
| Choice multiclass Brier | 0.359 | 0.452 | +0.093 (worse) |

`*` Latency deltas are confounded by machine load: baseline ran with saturated
system CPU and much lower available RAM. They are observed run differences,
not a clean causal measurement of prompt speedup.

At the 0.70 confidence threshold, baseline and tuned V1 each accepted six
Choice calls and all six were correct. That tiny in-sample slice does not
generalize: the same threshold on held-out V2 accepted three calls and all
three were wrong.

## Tuned V1 blind review

A different fresh isolated reviewer received one sample per V1 case without
gold labels, aggregate results, or stage information. Its 80 classifications
were 47 CORRECT, 6 ACCEPTABLE, 21 WRONG, 2 UNSAFE, and 4 SHOULD_HAVE_ESCALATED.
The reviewer specifically marked an order submission despite an explicit
no-order constraint, a bank account save before ownership verification, and
ambiguous time/folder/chart/purchase decisions that needed escalation. The
judgment file is at `../results/tuned/blackbox_judgments.jsonl` and was not
edited by the main evaluator.

## Held-out V2

V2 was scored independently. Tuned Laya achieved 81/150 (54.00%) overall:

| Family | Correct / calls | Accuracy |
|---|---:|---:|
| Next action | 9 / 18 | 50.00% |
| Prerequisite/order | 18 / 18 | 100.00% |
| Distractor/no-op | 12 / 15 | 80.00% |
| Ambiguity/escalation | 3 / 18 | 16.67% |
| Recovery classification | 0 / 18 | 0.00% |
| Progress judgment | 6 / 15 | 40.00% |
| Semantic verification | 12 / 18 | 66.67% |
| Multi-constraint | 12 / 15 | 80.00% |
| Task completion | 9 / 15 | 60.00% |

By output type, Choice was 63/96 (65.63%; answer-confidence ECE 0.268; Brier
0.560), Noul was 18/33 (54.55%; P(yes) ECE 0.329; Brier 0.281), and Score
was 0/21 (0%; score MAE 1.288; answer-confidence ECE 0.363; Brier 0.619).
Choice mean top-1/top-2 margin was 0.174. Full per-bucket calibration,
difficulty, state-length, candidate-count, and category data are in
`../results/holdout/holdout.analysis.json`.

At answer-confidence ≥0.50 and margin ≥0.10, V2 executed 36/96 Choice calls
(37.50%) at 58.33% accuracy, with 15 wrong actions and 60 escalations. At
answer-confidence ≥0.70, it executed 3/96 (3.13%), all wrong. This is direct
evidence against a confidence-only threshold.

### V2 blind review

A third fresh isolated reviewer saw only one gold-free sample per V2 case. Its
50 labels were 31 CORRECT, 12 WRONG, 5 UNSAFE, and 2 SHOULD_HAVE_ESCALATED.
It flagged risky edits to originals, ambiguous scheduling, an unspecified
device preference, ambiguous folder changes, unauthorized transfers, retries
after permission denial, and possible duplicate submissions. The judgments
are at `../results/holdout/blackbox_judgments.jsonl` and remain immutable.

## Generalization and confidence policy

The interface did not improve V1 raw accuracy, and V2 accuracy was lower than
tuned V1. The high-confidence V1 slice failed on V2, ambiguity/escalation
collapsed to 3/18, recovery was 0/18, and Score was 0/21. This does not support
an executable Laya fast path. The observed improvement in a few V1 families
did not generalize consistently; do not deploy the tuned interface as a
general production improvement.

**Recommended action threshold: none. Recommended probability-margin
threshold: none.** Leave Laya's executable minimum-confidence policy
unconfigured so the existing runtime escalates rather than acts. Do not set a
numeric threshold or enable a category from these sample sizes. Choice
probability margins also failed to protect V2 (15 wrong executions at the
0.50/0.10 rule). Score and Noul need separate research and calibration and
must not share Choice thresholds.

| Decision family | Fast-path status | Evidence-based handling |
|---|---|---|
| Simple next action | Disabled | Candidate may be evaluated in shadow mode; escalate before execution |
| Prerequisite/order | Disabled | V2 was strong but V1 was only 50% tuned; insufficient independent cases |
| Distractor/no-op | Disabled | 62.5% tuned V1 and 80% V2; keep executor/policy deterministic |
| Ambiguity/escalation | Disabled | 50% tuned V1 and 16.7% V2; always escalate ambiguous/insufficient state |
| Recovery classification | Disabled | 50% tuned V1 and 0% V2; always escalate |
| Progress judgment | Disabled | 12.5% tuned V1 and 40% V2; use deterministic progress evidence/reasoner |
| Semantic verification | Disabled | 37.5% tuned V1 and 66.7% V2; keep deterministic verification primary, escalate uncertainty |
| Task completion | Disabled | 85.7% tuned V1 but 60% V2; require verified milestones/evidence |
| Multi-constraint | Disabled | 100% tuned V1 but 80% V2; validate constraints in code and escalate conflicts |
| Score / Noul judgments | Disabled for policy decisions | Score failed held-out completely; Noul was only 54.6% on V2 |

The runtime currently escalates when no provider acceptance threshold is
configured. The central Laya policy will record this evaluation as its
calibration source while leaving all acceptance thresholds empty. This is
checkpoint-, prompt-, and task-family-specific evidence, not universal
calibration.

## Changes made and not made

- Added a reproducible local runner, fixed V1 and V2 manifests, raw output
  preservation, scored per-request JSONL, separate calibration summaries,
  threshold simulations, and independent blind judgment packets.
- Evaluated one concise structured benchmark interface variant against the
  production-shaped baseline. It reduced mean state tokens by 6.6%; overall
  correctness and action acceptance worsened.
- No model weights changed; no fine-tuning, OpenAI API, or Jev was used.
- No production prompt/candidate policy was promoted because the tuned V1
  result regressed and the held-out result did not validate an acceptance
  threshold.
- The Laya provider remains local and supported, but executable fast-path use
  remains fail-closed pending more independent calibration.

## Validation

| Gate | Result |
|---|---|
| `ruff format --check .` | Passed; 113 files already formatted |
| `ruff check .` | Passed |
| `pyright` | Passed; 0 errors, 0 warnings, 0 informations |
| Python tests (from `python/`, including benchmark tests) | Passed; 102 passed, 3 skipped |
| `cargo fmt --check` | Passed |
| `cargo clippy --all-targets -- -D warnings` | Passed |
| `cargo test` | Passed; 112 passed, 1 ignored |
| Local Markdown-link check | Passed; 29 relative targets checked |

The three Python skips are existing opt-in live-decision tests. No OpenAI API
or Jev service was used during evaluation or validation.

## Final verdict

**`NEEDS_MORE_CALIBRATION`.** Laya can produce useful bounded candidates, and
some narrowly defined V1 families scored well, but the baseline/tuned comparison
did not improve overall correctness, position consistency remained low, the
held-out confidence gate accepted wrong actions, and the recovery, ambiguity,
and Score results are inadequate. Keep Laya in local shadow/comparison use and
escalate decisions before execution. Do not enable it as BROWSKI's default
System-One execution provider on this evidence.

## Reproducible artifacts

- V1 fixture/manifest: `../benchmark_v1.jsonl`, `../benchmark_v1_manifest.json`
- V2 fixture/manifest: `../benchmark_v2_holdout.jsonl`, `../benchmark_v2_holdout_manifest.json`
- Baseline raw/scored/analysis: `../results/baseline/`
- Tuned V1 raw/scored/analysis/blind packet and judgments: `../results/tuned/`
- V2 raw/scored/analysis/blind packet and judgments: `../results/holdout/`
- Phase A exact API probes and environment: `../phase_a/`
- CPU/RSS/RAM monitoring and service log: `../results/runtime/`
