# System overview

Current BROWSKI architecture and implementation boundary. M0–M7 provide the
Rust browser runtime, semantic observation, typed action execution, Python
LangGraph orchestration, structured GPT-6 Luna decisions, durable task
checkpoints, bounded working memory, progress tracking, recovery budgets, and
high-risk confirmation. Luna is the only active action selector. Laya is
shadow-only and Jev is disabled. A local Rust action has a small-page latency
measurement; live provider quality, calibration, and latency remain unmeasured.

```mermaid
flowchart TB
    User([User task]) --> Runtime[Python Agent Runtime]
    Runtime --> TaskState[Task State]
    Runtime --> Memory[Working Memory]
    Runtime --> Planner[Planner]
    Runtime --> Progress[Progress Tracker]
    Runtime --> HLRecovery[High-level Recovery]
    Runtime --> Graph[LangGraph workflow\nserializable AgentState]
    Graph --> Gate[ComplexityGate\nlow normally; high on explicit promotion]
    Gate --> Luna[GPT-6 Luna\nstructured System Two]
    Luna --> Graph[LangGraph workflow\nserializable AgentState]
    Luna -. bounded choice comparison .-> Laya[Laya shadow only\nnever executes]
    Runtime --> Tools[Tool Registry]
    Tools --> Core[Rust Browser Core\nBrowserSession]
    Core --> Obs[Observation\nDOM + AX + layout]
    Core --> Registry[Element Registry\nstable refs]
    Core --> Exec[Executor\nactions]
    Exec --> Verify[Verification\npostconditions]
    Verify --> LLRecovery[Low-level Recovery\nbounded retries]
    Core --> Chromium[(Chromium)]
    Core -. planned routing .-> Vision[On-demand Vision\ncontract and capture primitive]
    Extension[MV3 side panel\nUI + debugger proxy] -. planned authenticated relay .-> Runtime
    Runtime --> Persist[(Persistence\nSQLite)]
    Runtime --> Telemetry[Telemetry\ntraces, provider-reported tokens]
    Telemetry <--> Core
```

## Component responsibilities

| Component | Owner | Role |
|---|---|---|
| Agent Runtime | Python | LangGraph observe/decide/execute/verify loop with bounded steps |
| Working Memory | Python | Compressed history, facts, milestones, failed strategies (bounded) |
| Planner | Python | Luna produces short milestone plans and bounded executable actions |
| Tool Registry | Python | Model-facing typed tools bridging into the Rust runtime |
| Provider Layer | Python | M5 provides shared Choice/Score/Noul, verification, recovery, and progress contracts; Laya is shadow-only, Jev disabled |
| Reasoning Layer | Python | M6 uses structured GPT-6 Luna output and deterministic low/high effort routing |
| Rust Browser Core | Rust | `BrowserSession`: Chromium process, tab/frame coordination, events |
| Observation | Rust | DOM + accessibility + layout → `SemanticSnapshot` |
| Element Registry | Rust | Stable refs (`@name`), fingerprints, reacquisition, generations |
| Executor | Rust | Validated actions only — no reasoning |
| Verification | Rust | `SUCCESS / FAILURE / UNCERTAIN` + evidence for every action |
| Low-level Recovery | Rust | Stale nodes, detached frames, nav races; bounded mechanical retries |
| Vision fallback | Python+provider | Typed contract and bounded screenshot capture exist; graph routing and screenshot privacy are pending |
| Checkpointing | Python | LangGraph thread checkpoints; `AgentRuntime.open_sqlite` uses the async SQLite saver and can resume after process exit |
| Telemetry | both | Trace events, timing, and provider-reported token usage; cost is not estimated |

## Key invariants

- The browser core never knows which LLM provider is in use.
- Laya and Jev implement the same low-level typed decision contract, but
  confidence is calibrated independently per provider. Current runtime policy
  permits only shadow comparison from Laya; it does not authorize actions.
- Browser infrastructure and reasoning stay in separate processes of
  responsibility (Rust vs Python), joined only by the versioned binding API.
- Frontend/browser-facing code talks through public APIs and events, never by
  linking agent internals.
- See `language-boundaries.md`, `verification-and-recovery.md`,
  `privacy-and-vision.md`, and `../protocols/versioning.md`.
