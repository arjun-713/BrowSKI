# ADR-005: Durable LangGraph checkpoints with SQLite

- Status: Accepted
- Date: 2026-10-02

## Context

The M4 graph originally used `InMemorySaver`, which loses task state when the
process exits. Resuming long-running browser work requires a durable checkpoint
store. The project has no database service, and the agent state is compact and
local to one runtime installation.

## Decision

- Use LangGraph's `AsyncSqliteSaver` for local durable graph checkpoints.
- Expose it through `AgentRuntime.open_sqlite`, an async context manager that
  owns and closes the SQLite connection.
- Keep `InMemorySaver` available through explicit dependency injection for
  isolated tests.
- Keep the persisted graph state serializable and exclude live browser/model
  objects from checkpoints.

## Consequences

The Python runtime adds the `langgraph-checkpoint-sqlite` package, which brings
`aiosqlite`. The SQLite saver is suitable for local, single-instance runtime
state; it is not a multi-host database. A process-restart fixture proves the
checkpoint can be reopened by another process. Restoring a task's browser
session after process exit remains a separate lifecycle concern; callers must
provide a live browser session when reconstructing `AgentRuntime`.

## References

- [LangGraph SQLite checkpoint package](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite)
- [M4 roadmap](../development/roadmap.md#m4-langgraph-agent-runtime-done)
