# BROWSKI Python runtime (`browser_agent`)

Python owns the autonomous agent runtime: planning, LLM orchestration,
working memory, task state, high-level recovery, provider abstraction,
evaluation, and benchmarking. The browser itself is owned by Rust
(`crates/`); Python reaches it through `browser_agent._core` (PyO3).

The installed `browski` CLI provides managed tasks, checkpoint resume, local
extension service, doctor, settings inspection and retention cleanup. Luna
is active, Laya is shadow-only, and Jev is disabled. Read the
[product README](../README.md), [repository rules](../AGENTS.md),
[architecture authority](../ARCHITECTURE_PLAN.md) and
[quality standard](../CODE_QUALITY.md).
