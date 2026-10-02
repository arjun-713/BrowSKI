# System overview

Current BROWSKI architecture and implementation boundary. M0–M4 provide the
Rust browser runtime, semantic observation, typed action execution, and a
minimal Python LangGraph loop. Laya/Jev routing, Luna reasoning, and durable
long-horizon recovery remain later milestones.

```mermaid
flowchart TB
    User([User task]) --> Runtime[Python Agent Runtime]
    Runtime --> TaskState[Task State]
    Runtime --> Memory[Working Memory]
    Runtime --> Planner[Planner]
    Runtime --> Progress[Progress Tracker]
    Runtime --> HLRecovery[High-level Recovery]
    Runtime --> Graph[LangGraph workflow\nserializable AgentState]
    Graph --> Providers[Injected decision agent\nM4 fake implementation]
    Runtime --> Tools[Tool Registry]
    Tools --> Core[Rust Browser Core\nBrowserSession]
    Core --> Obs[Observation\nDOM + AX + layout]
    Core --> Registry[Element Registry\nstable refs]
    Core --> Exec[Executor\nactions]
    Exec --> Verify[Verification\npostconditions]
    Verify --> LLRecovery[Low-level Recovery\nbounded retries]
    Core --> Chromium[(Chromium)]
    Core -.-> Vision[Screenshot / Vision fallback\nmultimodal provider]
    Runtime --> Persist[(Persistence\nSQLite)]
    Runtime --> Telemetry[Telemetry\ntraces, tokens, cost]
    Telemetry <--> Core
```

## Component responsibilities

| Component | Owner | Role |
|---|---|---|
| Agent Runtime | Python | LangGraph observe/decide/execute/verify loop with bounded steps |
| Working Memory | Python | Compressed history, facts, milestones, failed strategies (bounded) |
| Planner | Python | Next-action decisions; hierarchical planning later |
| Tool Registry | Python | Model-facing typed tools bridging into the Rust runtime |
| Provider Layer | Python | Provider abstractions exist; M4 injects a deterministic fake agent |
| Rust Browser Core | Rust | `BrowserSession`: Chromium process, tab/frame coordination, events |
| Observation | Rust | DOM + accessibility + layout → `SemanticSnapshot` |
| Element Registry | Rust | Stable refs (`@name`), fingerprints, reacquisition, generations |
| Executor | Rust | Validated actions only — no reasoning |
| Verification | Rust | `SUCCESS / FAILURE / UNCERTAIN` + evidence for every action |
| Low-level Recovery | Rust | Stale nodes, detached frames, nav races; bounded mechanical retries |
| Vision fallback | Python+provider | Screenshots to a multimodal model when native semantics are insufficient |
| Checkpointing | Python | LangGraph thread checkpoints; M4 default is in-memory, durable SQLite is future work |
| Telemetry | both | Trace events, timing, tokens, cost |

## Key invariants

- The browser core never knows which LLM provider is in use.
- Browser infrastructure and reasoning stay in separate processes of
  responsibility (Rust vs Python), joined only by the versioned binding API.
- Frontend/browser-facing code talks through public APIs and events, never by
  linking agent internals.
- See `language-boundaries.md`, `verification-and-recovery.md`,
  `privacy-and-vision.md`, and `../protocols/versioning.md`.
