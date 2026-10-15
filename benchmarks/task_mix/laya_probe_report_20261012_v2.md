# Laya explicit-command probe — 2026-10-12

## Protocol

This is a controlled probe of the local Laya model, not a browser task-success benchmark. It used 24
synthetic user tasks, frozen before inference (`laya_probe_frozen_20261012_v2.jsonl`, SHA-256
`b2e2381ff1dbcf441a6ce57b75602e78fc3773dcb127da78c982bba3a1cbd137`). The scoped request template is
`explicit-command-v1` with SHA-256
`e2d63c893f7350f436eb0b12816d260f320418376d7c4d7ee50c5c8b98adbd0f`. No held-out task file was read,
no browser was controlled, no OpenAI or Jev call was made, and no Laya weights were modified.

The broad arm sent the full semantic candidate set, distractors, and `ESCALATE_TO_REASONER` for all
24 tasks. The scoped arm used the production explicit-command template with only
`EXECUTE_AUTHORIZED_COMMAND` and `ESCALATE_TO_REASONER`; it queried only the locally eligible cases.
The other 4 cases were marked out-of-family without a scoped model call.

Environment: endpoint `http://127.0.0.1:8001`, model `laya-rl-agent`, routing model `english`,
device `cpu`. The loaded English model revision was `7b928d828b7b0e022f929d9bd2e44165aa270148`. Raw
request, answer, answer confidence, probabilities, margin, latency, and response are retained per
trial in `laya_probe_results_20261012_v2.jsonl`. Thresholds below use Laya's `answer_confidence`
field; its separate `confidence` field is also retained in each raw record.

## Observed results

| Arm | Canonical cases | Correct | Cases with order probes | Selection consistency | Median latency |
|---|---:|---:|---:|---:|---:|
| Broad candidates | 24 | 20 | 12 | 58.3% | 3396 ms |
| Scoped explicit command | 20 | 20 | 12 | 100.0% | 1077 ms |

The broad arm's threshold-grid point with the best observed accepted accuracy was answer confidence
≥0.5, margin ≥0.0: coverage 20.8%, 5/5 correct accepted decisions, 0 wrong executions.

The scoped arm's best observed point was answer confidence ≥0.0, margin ≥0.0: system coverage 83.3%
of all 24 tasks, 20/20 accepted decisions correct. Code-side eligibility excludes ambiguous,
conflicting, missing-information, and other unsupported tasks before this arm can query Laya.

### Threshold grid (selected margins)

Broad arm (threshold applies to answer confidence):

| Confidence | Margin | Accepted | Correct | Wrong executions | Coverage | Accepted accuracy |
|---:|---:|---:|---:|---:|---:|---:|
| 0.0 | 0.0 | 24 | 20 | 4 | 100.0% | 0.8333333333333334 |
| 0.0 | 0.2 | 7 | 6 | 1 | 29.2% | 0.8571428571428571 |
| 0.0 | 0.4 | 2 | 2 | 0 | 8.3% | 1.0 |
| 0.5 | 0.0 | 5 | 5 | 0 | 20.8% | 1.0 |
| 0.5 | 0.2 | 5 | 5 | 0 | 20.8% | 1.0 |
| 0.5 | 0.4 | 2 | 2 | 0 | 8.3% | 1.0 |
| 0.6 | 0.0 | 0 | 0 | 0 | 0.0% | — |
| 0.6 | 0.2 | 0 | 0 | 0 | 0.0% | — |
| 0.6 | 0.4 | 0 | 0 | 0 | 0.0% | — |
| 0.7 | 0.0 | 0 | 0 | 0 | 0.0% | — |
| 0.7 | 0.2 | 0 | 0 | 0 | 0.0% | — |
| 0.7 | 0.4 | 0 | 0 | 0 | 0.0% | — |
| 0.8 | 0.0 | 0 | 0 | 0 | 0.0% | — |
| 0.8 | 0.2 | 0 | 0 | 0 | 0.0% | — |
| 0.8 | 0.4 | 0 | 0 | 0 | 0.0% | — |
| 0.9 | 0.0 | 0 | 0 | 0 | 0.0% | — |
| 0.9 | 0.2 | 0 | 0 | 0 | 0.0% | — |
| 0.9 | 0.4 | 0 | 0 | 0 | 0.0% | — |

Scoped arm (threshold applies to answer confidence):

| Confidence | Margin | Accepted | Correct | Wrong executions | Coverage of 24 | Accepted accuracy |
|---:|---:|---:|---:|---:|---:|---:|
| 0.0 | 0.0 | 20 | 20 | 0 | 83.3% | 1.0 |
| 0.0 | 0.2 | 20 | 20 | 0 | 83.3% | 1.0 |
| 0.0 | 0.4 | 18 | 18 | 0 | 75.0% | 1.0 |
| 0.5 | 0.0 | 20 | 20 | 0 | 83.3% | 1.0 |
| 0.5 | 0.2 | 20 | 20 | 0 | 83.3% | 1.0 |
| 0.5 | 0.4 | 18 | 18 | 0 | 75.0% | 1.0 |
| 0.6 | 0.0 | 20 | 20 | 0 | 83.3% | 1.0 |
| 0.6 | 0.2 | 20 | 20 | 0 | 83.3% | 1.0 |
| 0.6 | 0.4 | 18 | 18 | 0 | 75.0% | 1.0 |
| 0.7 | 0.0 | 18 | 18 | 0 | 75.0% | 1.0 |
| 0.7 | 0.2 | 18 | 18 | 0 | 75.0% | 1.0 |
| 0.7 | 0.4 | 18 | 18 | 0 | 75.0% | 1.0 |
| 0.8 | 0.0 | 12 | 12 | 0 | 50.0% | 1.0 |
| 0.8 | 0.2 | 12 | 12 | 0 | 50.0% | 1.0 |
| 0.8 | 0.4 | 12 | 12 | 0 | 50.0% | 1.0 |
| 0.9 | 0.0 | 3 | 3 | 0 | 12.5% | 1.0 |
| 0.9 | 0.2 | 3 | 3 | 0 | 12.5% | 1.0 |
| 0.9 | 0.4 | 3 | 3 | 0 | 12.5% | 1.0 |

## Policy conclusion

No production routing threshold is recommended from this probe alone. It has only 20 independent
in-scope tasks; repeated order permutations are not independent examples. The scoped result also
measures only the narrow explicit-command question and cannot establish safety on general page
decisions. Continue to fail closed unless separate task-success and safety evidence validates a
checkpoint-specific threshold.

In the broad arm, the model selected an executable action instead of escalation for all four
deliberately unsafe or unsupported cases. This makes broad candidate selection unsuitable for
routing on this evidence, regardless of aggregate accuracy.

The apparent broad accuracy or scoped coverage is not a task-completion claim. A wrong broad answer
is counted as a wrong execution under each simulated threshold; no action actually executed. Scoped
wrong-execution count is structurally zero for in-scope cases because local code binds the only
executable answer to the exact authorized command. Out-of-family cases are rejected before model
inference.
