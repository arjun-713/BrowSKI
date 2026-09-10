# Agent loop (future)

```
UNDERSTAND → PLAN → OBSERVE → DECIDE → ACT → VERIFY → UPDATE
    → CHECK PROGRESS → RECOVER → REPEAT
```

| Phase | Meaning |
|---|---|
| UNDERSTAND | Parse the user task into goals and constraints. |
| PLAN | Produce or refine a plan (hierarchical in later milestones). |
| OBSERVE | Collect a `SemanticSnapshot` from the Rust core (never trust stale state). |
| DECIDE | LLM resolves ambiguity → one typed tool call (deterministic ops preferred once intent is known). |
| ACT | Rust executor performs the validated action. |
| VERIFY | Postconditions checked against before/after state; evidence recorded. |
| UPDATE | Working memory + task state updated (compressed, bounded). |
| CHECK PROGRESS | Completion criteria, partial progress, stagnation detection. |
| RECOVER | Low-level retry (Rust) or replan/alternate-strategy/escalate (Python). |

## Why it is not implemented yet

The scaffold (v0.1) validates the architecture and toolchain: Rust compiles,
bindings compile, Chromium launches, navigation + observation + shutdown work.
Building the loop before observation, element identity, executor, and
verification exist would cement the wrong abstractions. The loop lands in
Milestone 4 on top of those primitives; its lifecycle contract already lives
in `python/src/browser_agent/agent/runtime.py`.
