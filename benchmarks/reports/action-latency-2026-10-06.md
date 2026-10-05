# Local action latency study — 2026-10-06

## Method

Command:

```bash
cargo test -p browser-agent-core --test action_latency -- --ignored --nocapture
```

The test used Google Chrome Stable 154.0.8037.57, Rust 1.98.1, Fedora 44,
and an Intel Core i5-8350U CPU. It performed five warmups and 40 measured
iterations on a deterministic local `data:` page with a single checkbox.
Each measured iteration took one separate semantic observation to resolve the
current target, then executed and verified a typed checkbox action. No model
provider or network request was used.

## Results

All values are milliseconds. Values below one millisecond are rounded down to
zero by the current `u64` millisecond timing fields.

| Phase | p50 | p95 | p99 |
|---|---:|---:|---:|
| Separate semantic observation | 7 | 10 | 17 |
| Total `ActionOutcome.elapsed_ms` | 427 | 432 | 458 |
| Pre-action observation | 7 | 8 | 11 |
| Target resolution | 0 | 0 | 0 |
| Browser input execution | 7 | 8 | 10 |
| Mechanical recovery | 0 | 0 | 0 |
| Bounded settle | 404 | 406 | 406 |
| Post-action observation | 7 | 8 | 36 |
| Snapshot delta | 0 | 0 | 0 |
| Deterministic verification | 0 | 0 | 0 |

The measured settle phase dominates this small-page action, at about 404 ms
median. This is a latency observation, not a performance improvement claim.
Phase totals may not exactly equal end-to-end totals because event/tab handling
and other coordination overhead is included only in the total; millisecond
rounding also removes sub-millisecond phase values.

## Comparison limits

The existing M1 navigation and tab-cycle numbers and M2 observation range in
[`../../docs/development/roadmap.md`](../../docs/development/roadmap.md) are
historical measurements from different operations and page fixtures. They do
not establish a before/after comparison with this one-checkbox study. Repeat
the same named harness and environment for any future comparison. This result
also does not represent full task, provider, or long-horizon latency.
