# benchmarks

The benchmark suite records reproducible browser and agent measurements. The
metric set and comparison rules are in `docs/benchmarks/evaluation-plan.md`.

- `synthetic/` — deterministic local pages we control (first harness).
- `browsergym/` — BrowserGym/AgentLab integration (primary external suite).
- `reports/` — curated Markdown summaries are tracked; raw machine outputs are
  gitignored.

## Local action latency

The opt-in Rust harness measures a local semantic observation and typed action
against a deterministic data-URL page. It does not call a decision provider.
Run it with:

```bash
cargo test -p browser-agent-core --test action_latency -- --ignored --nocapture
```

The harness performs five warmups and 40 measured samples. It reports p50,
p95, and p99 for total action time and the executor's non-overlapping phase
timings. `elapsed_ms` is total wall time; phase values are integer
milliseconds, so values below one millisecond appear as zero. Preserve the
environment, browser version, page shape, warmup count, and sample count with
every comparison. See
[`action-latency-2026-10-06.md`](reports/action-latency-2026-10-06.md) for the first
measured run and its limits.
