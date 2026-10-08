# Language boundaries

## Why Rust (browser core)

Low-level browser runtime, CDP, event processing, DOM/state handling, element
identity, diffing, action execution, verification primitives, low-level
recovery, and performance-sensitive infrastructure. Reasons: zero-cost control
over processes/sockets/timeouts, fearless concurrency with Tokio, and a type
system that makes invalid browser states unrepresentable. The borrow checker
is doing real work here — session lifetimes and generation tracking are
compile-time properties.

## Why Python (agent runtime)

Planning, LLM orchestration, working memory, task state, high-level
recovery/replanning, provider abstraction, evaluation, benchmarking,
experimentation. Reasons: Python supports the graph orchestration, typed
schemas, and provider SDK adapters used by the agent. Iteration speed on
prompts, planners, and policies matters, while the browser core should change
only when browser mechanics or measured performance require it.

## Why TypeScript (browser-facing)

WXT/React Manifest V3 extension, side-panel task controls, trace viewer,
permission broker and browser-facing integrations. The extension relays an
allowlisted debugger transport and maintains its owned Chrome-tab mapping;
Rust interprets browser state and verifies actions. TypeScript does not plan,
route models, recover tasks, or mirror the semantic engine.

## When Bun is appropriate

TypeScript development/runtime where it measurably improves iteration speed:
dev tooling, scripts, UI tooling. It is not automatically the browser core,
and Node compatibility must be weighed for any distributed library.

## When Go would be justified

Isolated high-throughput services (e.g. a crawl/extraction fleet endpoint)
*if benchmarks justify it*. Adding Go for architectural variety is a no-go;
the ADR bar applies.

## Cross-language communication

- Python ↔ Rust: PyO3 bindings (`crates/python-bindings` → `browser_agent._core`),
  sync Rust surface adapted to `asyncio` via `to_thread`. Serialized contracts
  (`SemanticSnapshot`, `TraceEvent`) are JSON with versioned schemas.
- Frontend ↔ everything: public APIs and event streams, never shared runtime
  internals.
- Subsystem interfaces stay language-independent where practical so any side
  can be reimplemented without renegotiating the architecture.

## Dependency direction (normative)

**Rust must not depend on Python domain logic. Python may depend on Rust
bindings. Frontend communicates through public APIs/events rather than
linking against agent internals.**
