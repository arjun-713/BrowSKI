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
SQLite-backed CLI runs also record only run ID, timestamps, status, and bounded
step/reasoning counts. `browski runs clean` previews checkpoint removal by age;
deletion requires `--apply` and removes matching LangGraph checkpoint and write
rows in one SQLite transaction. Runs marked `running` are excluded unless
`--include-running` is explicitly supplied after confirming no runtime still
owns them. Task text, URLs, page content, and action values are not added to
the run metadata table.

Progress distinguishes visible semantic changes from activity. Completion
requires a successful verified action, required milestones, and any configured
visible evidence; a model `done` claim alone is rejected. Repeated failures use
explicit bounded recovery budgets. High-risk actions pause at a LangGraph
interrupt until the caller supplies an approval decision.

The in-process `AgentRuntime` also exposes cooperative pause and stop controls.
Pause checkpoints at a graph boundary before a new action and resumes from the
same run. Stop prevents the next action; if an action is already in flight, its
verification completes before the run becomes stopped. A run waiting for user
input is marked stopped directly in its checkpoint. These controls are runtime
APIs only; the local service and extension do not yet expose them.

The runtime can also send versioned, content-minimal lifecycle events through
an optional asynchronous sink. Events identify the run and step and report
fixed lifecycle labels for observation, decision, action, verification,
recovery, confirmation, and terminal state. They omit task text, page content,
provider reasoning, and action values. A sink failure disables trace delivery
without interrupting browser execution. The authenticated Native Messaging
service forwards these events to the extension side panel.

Local tests cover an 11-step long-horizon workflow, text-only progress, bounded recovery,
completion evidence, and confirmation approval/denial. Luna-backed normal and
high reasoning recovery use the concrete M6 provider seam and deterministic
`ComplexityGate`. Normal reasoning uses low effort; high effort is confined to
the high-replan rung. Structured milestone evidence must appear in a later
semantic observation before it can count as complete. The task CLI can persist
and reopen graph checkpoints after process restart. Resume starts a fresh
browser session and re-observes before acting; it does not attach to the prior
Chromium process or restore page-local state.
