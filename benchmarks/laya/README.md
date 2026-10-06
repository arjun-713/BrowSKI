# Laya decision benchmark

This harness evaluates the fixed JSONL cases in `benchmark_v1.jsonl` through
the existing `LayaProvider` and records raw request/response evidence. It has
three separate stages: run the baseline, inspect its analysis, then run the
tuned prompt. Do not start baseline collection until the fixture has been
reviewed, frozen, and committed. Do not combine baseline and tuned runs.

The completed 2026-10-06 evaluation also includes a frozen 50-case
`benchmark_v2_holdout.jsonl`. Its checksum was committed before inference, and
the tuned V1 interface was not changed after V2 results. See
`reports/laya-calibration-report.md` for the evidence-based policy verdict.

## Fixture shape and model boundary

Each line follows the typed schema in `schema.py`: case/category/difficulty,
task and current subgoal, browser state (including optional noise elements),
recent action/outcome, relevant delta, constraints, question type, question,
candidates, Score criteria, gold answer(s), rationale, and `position_probe`.
The model request contains only task context, browser evidence, the question,
and allowed candidates or Score labels. Gold answers, rationale, and category
are kept in the local result/evaluation path and are never sent to Laya.
Choice candidates are sent with provider-compatible IDs. Any authored Noul
YES/NO pseudo-candidates remain local and are omitted from the Noul request.

Choice candidate IDs sent to Laya are `c01`, `c02`, …, matching
`select_action_candidate`; captured outputs map those IDs back to fixture
`semantic_id` values. The baseline uses the production selector's state,
candidate description, and prompt construction, including the complete current
element list. Tuned context is benchmark-only and passes structured task,
subgoal, constraints, relevant elements, recent action/outcome/delta, full
candidate descriptions, and explicit single-action, prerequisite, and
escalation instructions.

Fixture elements use `semantic_id` and may encode `state` as a string. The
adapter maps `semantic_id` to the selector's `ref`, wraps scalar state as one
state label, and infers `interactable` only from standard actionable roles when
the fixture does not provide it. Score questions must put the exact evaluated
proposal, sequence, or claim in `question`, after a marker such as
`Proposed action: ...`; the schema rejects generic Score questions without the
item being scored. Score accuracy rounds the provider's continuous score to
the nearest rubric integer with half-up ties; Score MAE retains the continuous
value. Noul preserves raw `p_yes`; its binary accuracy uses 0.5 only to report
the yes/no answer for this benchmark, while Brier uses unthresholded yes/no
probabilities.

Each case gets three canonical-order repeats. `position_probe` Choice cases
then receive three additional calls with fixed candidate permutations: reverse,
left rotation, and right rotation. The seed controls the order in which these
permutation variants run; canonical repeats keep their original order.

## Baseline → analysis → tuned

Run from the Mango repository root. Use the reviewed fixture path supplied by
the benchmark owner:

```bash
PYTHONPATH=python/src python -m benchmarks.laya.run_baseline \
  --input benchmarks/laya/benchmark_v1.jsonl \
  --output benchmarks/laya/results/baseline.jsonl \
  --checkpoint benchmarks/laya/results/baseline.checkpoint.jsonl \
  --variant baseline --repeats 3 --seed 20261006
```

Inspect the baseline report before running tuned:

```bash
PYTHONPATH=python/src python -m benchmarks.laya.evaluate \
  --input benchmarks/laya/results/baseline.jsonl \
  --cases benchmarks/laya/benchmark_v1.jsonl \
  --output benchmarks/laya/results/baseline.analysis.json
```

Only after reviewing that report, run tuned separately. The runner requires an
analysis report that identifies an existing baseline results file:

```bash
PYTHONPATH=python/src python -m benchmarks.laya.run_baseline \
  --input benchmarks/laya/benchmark_v1.jsonl \
  --output benchmarks/laya/results/tuned.jsonl \
  --checkpoint benchmarks/laya/results/tuned.checkpoint.jsonl \
  --variant tuned --analysis benchmarks/laya/results/baseline.analysis.json \
  --repeats 3 --seed 20261006
```

`--offline-responses <jsonl>` replays captured response bodies instead of
opening the endpoint. Replay rows must contain parsed `response` and literal
`response_raw` fields. It is useful for plumbing checks; the output must not be
described as a new live inference run. No test in this directory calls a live
service. Do not expose credentials in command lines or result files.

For service CPU, RSS, system RAM, and warm-cache cold-start monitoring, the
independent helper is:

```bash
python benchmarks/laya/monitor_service.py --serve-command <path> ...
```

It writes `results/runtime/service_metrics.jsonl` and
`results/runtime/server.log`. Use the wrapper's current `--help` output for
the serve-command arguments and preserve its measurements beside each run.

## Output and interpretation

The JSONL run output and checkpoint preserve the request payload object, exact
UTF-8 HTTP response body, HTTP status and response headers, timestamp, model,
routing object, raw confidence fields, raw probabilities, usage, latency,
repeat/permutation index, and errors where available. Request authorization
headers are deliberately omitted. Request payloads are recorded as parsed
objects, not byte-for-byte HTTP serialization. Laya-reported token values and
confidence/probability fields are recorded as returned; the harness does not
estimate tokenization, cost, or provider confidence quality.

The evaluator reports accuracy by category and question type, separate ten-bin
calibration summaries for `confidence` and `answer_confidence`, ECE and Brier
score by question type, top-1/top-2 margin, coverage/accepted accuracy over
confidence thresholds 0.50–0.90 and confidence-plus-margin grids, wrong
actions, escalations, abstention accuracy, latency percentiles, token totals,
canonical repeat agreement, and permutation-only consistency. It also reports
difficulty, candidate-count, provider-reported state-token-length, and
error-type breakdowns. These thresholds are
descriptive benchmark slices only; they are not production routing or
acceptance thresholds.

Use `--scored-output <jsonl>` with the evaluator to write every call as a
separate scored row. This file adds evaluator-only expected/acceptable answers,
rationale, difficulty, and correctness to a copy of each raw record. These
labels are not present in the request payload. Keep this scored JSONL beside,
not in place of, the unmodified request/response run log.

Independent qualitative reviews use one canonical, gold-free row per case.
Their output files live beside each phase's raw records. The main evaluator
preserves them unchanged; deterministic fixture labels remain the primary
quantitative ground truth.

Raw HTTP bodies and run outputs are evidence, not proof of task success. This
is a model decision benchmark over authored cases, not browser end-to-end task
completion. It does not establish that an action executed or was verified by a
browser. Preserve the fixture hash, environment, Laya service/model revision,
run seed, and runtime monitor output when interpreting comparisons.
