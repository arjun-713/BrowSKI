# ADR-001: Polyglot architecture

Date: 2026-09-10 · Status: accepted

## Context

The system needs a low-level browser runtime (CDP, DOM/state, actions,
verification) and an autonomous agent runtime (planning, LLM orchestration,
memory, eval). One language could cover both, but browser control rewards
control and performance while agent intelligence rewards ecosystem and
iteration speed.

## Options considered

- **Python only** (Playwright + agent in one process). Fastest start, richest
  LLM/eval ecosystem — but the GIL, weaker process/lifetime control, and
  temptation to mix reasoning with transport in one codebase.
- **Rust only**. Best runtime properties, but the LLM/eval ecosystem is thin;
  prompt/planner experimentation would be slow and lonely.
- **Go-centric**. Strong networking story, but neither the browser-control nor
  the LLM-eval ecosystem is best-in-class; adds little over Rust+Python.
- **TypeScript/Bun only**. Natural for browser-facing code, weak for
  long-running agent state and eval harnesses; Playwright-in-JS reintroduces
  the single-runtime mixing problem.
- **Polyglot** (Rust browser core + Python agent + TypeScript browser-facing).

## Decision

Polyglot: **Rust** owns browser infrastructure, **Python** owns agent
intelligence, **TypeScript** owns browser-facing/frontend surfaces, **Bun**
only for dev tooling where measurably faster, **Go** only later with
benchmark justification.

## Tradeoffs

- Cost: two build systems (Cargo + uv/maturin), cross-language API discipline,
  contributors need comfort in two stacks for end-to-end work.
- Mitigation: language-independent interfaces, versioned contracts
  (`docs/protocols/versioning.md`), one sanctioned Pydantic mirror of Rust
  schemas, and `AGENTS.md` ownership tables so each change has one clear home.
- Benefit: each subsystem gets its best ecosystem; reasoning can never
  accidentally entangle with transport (different languages, enforced by the
  compiler/packaging boundary); benchmarking and experimentation stay fast.

## Consequences

- New languages need an ADR with a measurable benefit (see `AGENTS.md` §10).
- Cross-language API changes follow the versioning protocol, never ad-hoc.
