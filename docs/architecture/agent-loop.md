# Agent loop (M4–M7 runtime core)

```
OBSERVE → DECIDE → EXECUTE → VERIFY → REPEAT
```

| Phase | Meaning |
|---|---|
| OBSERVE | Collect the current `SemanticSnapshot` from the Rust core. |
| DECIDE | `LunaDecisionAgent` asks the configured `DecisionProvider` to choose from a finite semantic candidate set; abstention or planning ambiguity can route to structured GPT-6 Luna reasoning. |
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
high reasoning recovery use the concrete M6 provider seam and deterministic
`ComplexityGate`. Normal reasoning uses low effort; high effort is confined to
the high-replan rung. Structured milestone evidence must appear in a later
semantic observation before it can count as complete. The task CLI can persist
graph checkpoints, but a resumed runtime still needs a live browser session.
