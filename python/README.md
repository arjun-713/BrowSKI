# browser-agent (Python side)

Python owns the autonomous agent runtime: planning, LLM orchestration,
working memory, task state, high-level recovery, provider abstraction,
evaluation, and benchmarking. The browser itself is owned by Rust
(`crates/`); Python reaches it through `browser_agent._core` (PyO3).

See the repo root `README.md`, `AGENTS.md`, and `docs/`.
