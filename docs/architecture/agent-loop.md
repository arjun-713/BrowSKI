# Agent loop (M4–M7 runtime core)

```
OBSERVE → DECIDE → EXECUTE → VERIFY → REPEAT
```

| Phase | Meaning |
|---|---|
| OBSERVE | Collect the current `SemanticSnapshot` from the Rust core. |
| DECIDE | Injected `Agent` returns one typed `BrowserAction` or completion. |
| EXECUTE | Python passes the typed contract through PyO3; Rust resolves, acts, and verifies. |
| VERIFY | The graph accepts success only when Rust reports successful execution and verification. |
| REPEAT | Continue within configured step and decision limits. |

The graph state contains serializable task state, bounded structured working
memory, the latest observation, and capped action and recovery histories. Action
summaries omit submitted text and URL data. After verification, outcomes retain
only execution and verification status. The live `BrowserSession` and `Agent`
are closure dependencies and are never checkpointed. `AgentRuntime.open_sqlite`
owns an async SQLite saver for persistent threads; the explicit in-memory saver
remains useful for isolated tests.

Progress distinguishes visible semantic changes from activity. Completion
requires a successful verified action, required milestones, and any configured
visible evidence; a model `done` claim alone is rejected. Repeated failures use
explicit bounded recovery budgets. High-risk actions pause at a LangGraph
interrupt until the caller supplies an approval decision.

Local tests cover a 10-action workflow, text-only progress, bounded recovery,
completion evidence, and confirmation approval/denial. Luna-backed normal and
high reasoning recovery remains tied to M6 provider integration. Checkpoints
survive process exit, but a resumed runtime still needs a live browser session.
