# benchmarks

Harnesses land in Milestone 9; the scaffold defines the metric set and layout
so instrumentation can be built against a stable target. Plan:
`docs/benchmarks/evaluation-plan.md`.

- `synthetic/` — deterministic local pages we control (first harness).
- `browsergym/` — BrowserGym/AgentLab integration (primary external suite).
- `reports/` — machine-written results (gitignored except `.gitkeep`).
