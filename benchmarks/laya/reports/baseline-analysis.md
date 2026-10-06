# Laya V1 Baseline Analysis

## Scope and denominator

This analysis uses the frozen V1 fixture (`benchmark_v1.jsonl`, SHA-256
`d585b64c02132d127bf7915f7e0f650a7e9a282ea201fa41c62e7de959343fbb`). It
contains 80 deterministic cases and 240 canonical calls (three repeats each).
The 60 extra candidate-order probes are analyzed separately and are excluded
from accuracy, calibration, and threshold denominators. All 300 live requests
returned HTTP 200. The three canonical responses for each case were identical.
No expected answer was changed after collection.

Raw evidence: `../results/baseline/baseline.jsonl`; deterministic metrics:
`../results/baseline/baseline.analysis.json`; independent blind review:
`../results/baseline/blackbox_judgments.jsonl`.

## Primary results

Overall canonical accuracy is 153/240 (63.75%). This combines unlike output
types and is only a broad summary; per-kind results are more informative.

| Question type | Correct / calls | Accuracy | Additional metric |
|---|---:|---:|---|
| Choice | 120 / 147 | 81.63% | answer-confidence ECE 0.280; Brier 0.359 |
| Score | 12 / 33 | 36.36% | score MAE 0.821; answer-confidence ECE 0.142; Brier 0.627 |
| Noul | 21 / 60 | 35.00% | P(yes) ECE 0.326; binary Brier 0.322 |

Raw `confidence` is not a useful common acceptance signal: Choice ECE is 0.704,
Score ECE 0.325, and Noul ECE 0.326. `answer_confidence` behaves differently
by question type and is still materially miscalibrated. The checkpoint's
startup warning specifically identifies an unsupported/clamped temperature
for `choice:11+`; this does not mean every field is invalid, but the empirical
results show that none should be trusted without family-specific evidence.

## Category results

| Category | Correct / calls | Accuracy | Main observed risk |
|---|---:|---:|---|
| next_action | 39 / 45 | 86.67% | 6 wrong immediate actions |
| prerequisite_order | 21 / 30 | 70.00% | 6 wrong choices; 3 explicit escalations |
| distractor_noop | 15 / 24 | 62.50% | distractor selection remains common |
| ambiguity_escalation | 15 / 24 | 62.50% | 9 wrong answers versus 15 gold escalations |
| recovery_classification | 18 / 24 | 75.00% | 6 incorrect classifications |
| progress_judgment | 3 / 24 | 12.50% | progress judgments are not usable |
| semantic_verification | 9 / 24 | 37.50% | unsupported/incorrect verification judgments |
| task_completion | 15 / 21 | 71.43% | false completion remains possible |
| multi_constraint | 18 / 24 | 75.00% | 6 violations or incorrect decisions |

There are only 7–15 independent authored cases per category, each repeated
three times. Repeats verify deterministic behavior; they do not triple the
number of independent scenarios. Difficulty accuracy was 84.62% for easy
cases (33/39); the remaining medium/hard cases were weaker. The machine-readable
analysis includes the full difficulty, state-token, candidate-count, and
question-type slices. State size and candidate count correlate with authored
families here, so these descriptive buckets do not isolate causal effects.

## Confidence, margin, and routing simulation

Choice answer-confidence buckets had 0/6 correct in 0.3–0.4, 15/21 in
0.4–0.5, 51/60 in 0.5–0.6, 45/51 in 0.6–0.7, and 9/9 in 0.7–0.8. The
perfect highest populated bucket has only nine calls and no independent
scenario validation. It is not evidence for a production threshold.

| Choice acceptance rule | Coverage | Accepted accuracy | Wrong actions executed | Escalations |
|---|---:|---:|---:|---:|
| answer-confidence ≥ 0.50 | 71.43% | 85.71% | 15 | 42 |
| ≥ 0.50 and margin ≥ 0.10 | 67.35% | 90.91% | 9 | 48 |
| ≥ 0.50 and margin ≥ 0.20 | 61.22% | 90.00% | 9 | 57 |
| answer-confidence ≥ 0.60 | 34.69% | 88.24% | 6 | 96 |
| answer-confidence ≥ 0.70 | 4.08% | 100% | 0 | 141 |

The 0.70 row accepts six decisions only. Threshold simulations exclude explicit
escalation answers from executable actions. Current evidence supports
conservative escalation, not a numerical production threshold.

For Noul, Brier is 0.322 and ECE 0.326. `answer_confidence` represents
confidence in the selected binary answer, while `p_yes` is the evaluated
probability; these are not interchangeable. Score confidence also cannot be
interpreted as Choice confidence. Keep all three analyses separate.

## Abstention and position bias

The eight escalation cases generated 24 calls: 15 were explicitly escalated
and 9 selected an action (62.5% gold escalation accuracy). Across Choice
calls, explicit escalations were usually correct (abstention accuracy 91.84%),
but the ambiguous subset exposes the important failure: the model often acts
despite insufficient evidence.

The 60 position permutations achieved 20/60 accuracy (33.33%) and only 35%
semantic-answer consistency across permutations. Candidate position 1 was
selected 33 times, position 2 17 times, and position 3 10 times. These are
permutations of only 20 scenarios, so this is evidence of order sensitivity,
not 60 independent cases.

## Independent blind review

A separate evaluator received the context and one canonical Laya answer per
case without gold labels, rationales, aggregate scores, or stage information.
Its 80 judgments were: 50 CORRECT, 4 ACCEPTABLE, 22 WRONG, and 4 UNSAFE. It
marked no cases SHOULD_HAVE_ESCALATED or AMBIGUOUS_BENCHMARK. This is secondary
qualitative evidence; deterministic gold comparison remains primary. The
judgment file is preserved unchanged.

## Failure analysis and interface hypothesis

The baseline Choice request mirrors the production selector: it sends the
whole observed element list, omits explicit constraints and recent verified
action/outcome/delta, and asks only for the best candidate advancing the
subgoal. The tuned interface will test concise structured context that keeps
task, subgoal, constraints, relevant elements, recent action, outcome, and
delta, plus explicit prerequisite and escalation instructions. Candidate
descriptions remain complete semantic actions with provider IDs mapped back
to stable semantic IDs.

This is an interface hypothesis, not a claim that prompt changes solve weak
Score/Noul, progress, or verification performance. Those families will be
remeasured unchanged, and held-out V2 is required before generalizing a V1
gain. No examples will be removed or relabeled.

## Decision before tuning

Do not enable Laya execution from baseline evidence alone. Progress and
semantic-verification judgments should escalate; task completion,
multi-constraint, and ambiguous decisions should not be accepted solely on a
raw confidence threshold. Continue with the prespecified concise structured
interface experiment, then require held-out evidence and independent review.
