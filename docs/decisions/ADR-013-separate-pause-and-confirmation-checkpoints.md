# ADR-013: Separate pause from consequential-action confirmation

Date: 2026-10-08 · Status: accepted

## Context

The real extension lifecycle test exposed a pause checkpoint containing a
pending action risk assessment. Normal resume then refused to proceed because
it interpreted that checkpoint as an approval request. More seriously, placing
both interrupt kinds conditionally in the same node can confuse resume values:
LangGraph matches multiple interrupts by their order within a node.

## Decision

Give user pause its own graph node with one stable interrupt. At a safe pause
boundary, discard the unexecuted decision and pending approval flag while
preserving task state, memory, browser session, and trace. Resume acknowledges
only that pause and returns to observation and decision.

Keep high-risk confirmation in the safety node. Normal resume cannot approve
it; explicit approval/denial remains tied to the pending run checkpoint.
An action already in flight finishes verification before pause or stop takes
effect. Stop cancels an outstanding decision where supported.

## Consequences

Resume may need a fresh reasoning call because a paused action is discarded.
This prevents stale decisions or pause acknowledgments from becoming action
authorization. Pause and confirmation remain distinct across SQLite checkpoint
reconstruction.

## Validation

Runtime regressions cover pause/resume and stop at safe boundaries. Real
extension integration covers pause before execution, stop during a blocked
decision, submission denial, and pause/resume before a high-risk request.
Model performance and live API availability are outside these tests.

## Reference

[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
documents stable ordering and explicit resume values.
