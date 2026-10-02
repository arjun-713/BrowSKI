# Agent loop (M4 baseline)

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

The graph state contains serializable task state, bounded working-memory events,
the latest observation, decision, outcome, and a capped action history. The live
`BrowserSession` and `Agent` are closure dependencies and are never checkpointed.
`AgentRuntime.open_sqlite` owns an async SQLite saver for persistent threads;
the explicit in-memory saver remains useful for isolated tests.

M4 uses deterministic fake agents and local browser fixtures. It does not
include provider integrations, semantic decision routing, deep reasoning, or
stagnation recovery; those are separate M5–M7 capabilities. Checkpoints survive
process exit, but a resumed runtime still needs a live browser session.
