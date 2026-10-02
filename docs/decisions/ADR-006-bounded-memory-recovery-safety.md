# ADR-006: Bounded task memory, recovery, and consequential-action approval

- Status: Accepted
- Date: 2026-10-02

## Context

The LangGraph browser loop needs durable task progress without accumulating an
unbounded transcript or treating model output as proof that a task completed.
Repeated actions and uncertain verification also need explicit limits. Some
browser actions have consequential effects and require a user decision before
execution.

## Decision

- Store task goals, constraints, milestones, acquired facts, entities, failed
  strategies, pending questions, and recent events in bounded structured
  working memory.
- Track progress from semantic state, document and tab transitions, visible
  text, successful verification, milestone completion, and reduced subgoals.
- Bound stagnation samples, action history, and each recovery rung per run.
- Require a deterministic successful action, required milestones, and
  configured visible evidence before accepting completion.
- Pause high-risk actions at a graph interrupt until explicit approval or
  denial. Never infer consent from task wording or model output.
- Keep action summaries free of submitted values and URL data. After action
  verification, checkpoints retain only the execution/verification status
  needed by the next decision.
- Define System One, normal-reasoning, ComplexityGate, and high-reasoning
  recovery rungs. Concrete Luna routing is provided by M6 and is unavailable
  until that provider integration is complete.

## Consequences

The runtime can resume from bounded task and recovery state, and tasks with
text-only page changes count as progress. A task can stop or ask the user when
its configured budgets are exhausted. The graph still requires a live browser
session on resume; checkpoint restoration does not recreate Chromium. The
policy does not establish that a provider's confidence is calibrated.

## References

- [Agent loop](../architecture/agent-loop.md)
- [Verification and recovery](../architecture/verification-and-recovery.md)
- [Roadmap](../development/roadmap.md#m7-memory-progress-and-recovery-core-implemented)
- [ADR-005: Durable LangGraph checkpoints with SQLite](ADR-005-durable-agent-checkpoints.md)
