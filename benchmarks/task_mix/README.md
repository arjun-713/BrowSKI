# Seeded local task mix

This is a small, deterministic browser-task corpus for controlled BROWSKI
runs. It contains 18 development tasks and 9 held-out tasks, all backed by
static pages in `tests/fixtures/task_mix/`. Each case starts from a freshly
served local page. The fixtures make no external requests and cannot complete
a purchase or reservation.

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
