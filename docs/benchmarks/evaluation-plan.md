# Evaluation plan

## North-star metric

**TASK SUCCESS RATE** — fraction of tasks completed end-to-end, judged
against explicit completion criteria per task. This is the primary metric
(principle 1); everything below explains *why* it moved.

## Tracked alongside

- partial completion (milestone credit)
- number of steps
- number of LLM calls
- token usage (input/output)
- cost (USD)
- wall-clock latency
- action failure rate
- verification failure rate
- recovery success rate
- stagnation rate

## Integration targets (future, not yet integrated)

| Suite | Covers |
|---|---|
| BrowserGym | Gym-style web-task harness, multi-benchmark runner |
| AgentLab | Large-scale reproducible evaluation workflows |
| WebArena / WebArena-Verified | Self-hosted realistic web tasks |
| VisualWebArena | Vision-heavy tasks |
| WorkArena | Enterprise-workflow tasks |
| AssistantBench | Long-horizon assistant tasks |
| BU Bench | Browser-Use community benchmark |
| Mind2Web-family | Grounding/action-prediction evaluation where practical |

Phase the integrations: `benchmarks/synthetic/` first (deterministic local
pages we control), then BrowserGym as the primary external harness
(Milestone 9). Do not integrate everything at once; each integration must
report the full metric set above into `benchmarks/reports/`.

## Rules

- Benchmarks exist from the beginning; the scaffolding (`benchmarks/`,
  reports dir, metric definitions) is the Milestone 0 deliverable.
- Do not claim an improvement — or parity/superiority with any system —
  without measured numbers on a named suite.
