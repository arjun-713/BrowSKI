# Seeded local task mix

This is a small, deterministic browser-task corpus for controlled BROWSKI
runs. It contains 18 development tasks and 9 held-out tasks, all backed by
static pages in `tests/fixtures/task_mix/`. Each case starts from a freshly
served local page. The fixtures make no external requests and cannot create a
real purchase or reservation. Local reservation controls do change their
synthetic page state, which the evaluator checks independently.

## Corpus design

The task instructions use ordinary browser language, independent of BROWSKI's
internal target syntax. The mix covers unique button clicks, checkbox
combinations, native selects, quoted and unquoted text entry, filtering and
search, multi-stage forms, evidence transfer across tabs, prerequisite order,
explicitly missing information, and a high-risk confirmation boundary.

Each split has six small/medium/large development tasks or three small/medium/
large held-out tasks. Intended action counts follow the benchmark bands:
small 1–2, medium 3–5, large 6–10. `gold_action_count` counts the intended
browser or user-outcome decisions; `max_steps` is a separate run safety bound.

Gold checks describe browser state independently of the model's completion
claim: input values, checked controls, selected labels, exact visible text
markers, tab paths, ask-user outcome, confirmation status, and whether a
reservation was submitted. A pending confirmation case must leave
`submitted=false`.

## Use

`dataset.py` loads and validates one split, substitutes the runtime origin only
after loading, and shuffles with seed `20261012` by default. Local port numbers
never enter the source corpus or source checksum. Development-only loading is
the default:

```python
from benchmarks.task_mix.dataset import shuffled_suite

cases = shuffled_suite("http://127.0.0.1:43127")
```

The held-out data lives in its own file and is not included unless
`include_holdout=True` is passed explicitly. Keep held-out outcomes out of
prompt or policy tuning. Freeze the corpus checksum and exact seeded order
before the first model-backed run; record a separate run manifest with the
chosen split, resolved local URLs, runtime configuration, provider call counts,
and outcomes.

## Freeze record

The canonical seed is `20261012`. `freeze.sha256` records hashes for the
ordered development and held-out JSONL inputs and the combined corpus. The
seeded case order is recorded in `frozen-order.json`. These are source-only
identities: they contain no runtime port, provider response, or result data.
Do not replace a failed run's manifest or artifacts with a later attempt.

## Reproducible execution

From the repository root, retain the exact Python/native runtime before a
model-backed run. Runtime copies and raw debug records stay in ignored local
storage, with restrictive directory permissions:

```sh
python/.venv/bin/python -m benchmarks.task_mix.freeze_runtime \
  --output debug-logs/my-evaluation/frozen-runtime --label my-evaluation

python/.venv/bin/python -m benchmarks.task_mix.runner \
  --suite dev --variant optimized \
  --source-root debug-logs/my-evaluation/frozen-runtime/browser_agent \
  --output debug-logs/my-evaluation
```

This uses the existing configured OpenAI key and makes billable requests.
Every run writes a manifest, per-case `results.jsonl`, raw sanitized provider
records, a summary JSON and a case CSV. The deterministic evaluator alone
decides the primary success score. All attempts, including failures and
interruptions, must be retained.

`optimized` uses the bounded Luna runtime; it does not enable Laya execution.
The separate `prefer-laya` experiment requires an explicitly enabled scoped
policy. The supplied policy is disabled, and none of the reported mixed-task
or independent workflow runs uses executable Laya routing. Jev is never called.

`--budget-scale 3 --difficulty large` is an explicit extended-budget
development experiment. It scales original case bounds, capped at 180 seconds,
120 steps and the configured global call cap. It does not change gold or
retrospectively improve the original run. The manifest records the execution
policy. `--resume <run-directory>` continues only a matching frozen runtime,
corpus, policy and order; it does not rerun completed cases.

## Independent workflow holdout

`holdout_v3.jsonl` contains six independently authored workflows, two medium
and four large, with eight new local fixtures. Its manifest records the
checksum, fixture checksums, seed `20261015` and source order. It was committed
before inference in `395c9e9`. Do not use its outcomes for tuning.

After finalizing and freezing a runtime, run it with:

```sh
python/.venv/bin/python -m benchmarks.task_mix.runner \
  --suite holdout --variant optimized --seed 20261015 \
  --max-case-seconds 180 \
  --corpus benchmarks/task_mix/holdout_v3.jsonl \
  --source-root debug-logs/my-evaluation/frozen-runtime/browser_agent \
  --output debug-logs/my-evaluation
```

The explicit corpus loader validates bounds and IDs; its checksum overrides
the V1 split identity in the run manifest. Keep this result separate from V1
and extended-budget development scores. The explicit timeout honors V3's
native per-case bounds up to 180 seconds without multiplying its step or call
budgets; omitting it preserves V1's original 120-second global cap.

See the [V1 evaluation report](../../docs/development/task-mix-evaluation-2026-10-14.md)
and [long-task diagnostics](../../docs/development/long-task-diagnostics-2026-10-15.md),
plus the [prompt-cache evidence](../../docs/architecture/prompt-caching.md).
