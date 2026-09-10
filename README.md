# browser-agent

A general-purpose open-source browser agent: install the package, provide an
API key or a local model, give a natural-language browser task, and the agent
completes it autonomously.

```python
from browser_agent import BrowserSession

async with BrowserSession.launch() as browser:
    await browser.navigate("https://example.com")
    snapshot = await browser.observe()
    print(snapshot.title)  # Example Domain
```

> **Status: scaffold (v0.1).** The cross-language runtime works — Rust drives
> a live Chromium, Python orchestrates through PyO3 bindings — but there is
> **no autonomous agent loop yet**. No benchmark claims, no production-readiness
> claims. See [Roadmap](docs/development/roadmap.md).

## What "browser agent" means here

A program that takes a task like *"find AI internships in Bengaluru with
stipend above ₹20k and open the best five"* and carries it out in a real
browser: navigating, reading pages, filling forms (without submitting unless
asked), extracting structured data, opening tabs — verifying each step and
recovering from failures, over short and long horizons.

## Why this project exists

Existing systems (Browser Use, Stagehand, and others — see
[competitor notes](docs/research/competitor-notes.md)) each make sharp
tradeoffs: single-language runtimes, baked-in providers, vision-only
grounding, or closed cores. This project aims for an independent,
provider-agnostic, self-hostable runtime that competes on the metric that
matters — **end-to-end task completion** — while staying open and
benchmark-driven from day one.

## High-level architecture

```
USER TASK
   |
   v
PYTHON AGENT RUNTIME  (planning, memory, providers, recovery, eval)
   |
   v
RUST BROWSER CORE     (CDP, observation, element registry, executor,
                        verification, low-level recovery)
   |
   v
CHROMIUM
```

Optional/complementary: screenshot/vision as a *fallback sensor* through any
multimodal provider (local perception and privacy filtering arrive as modular
add-ons, not as the default pipeline).

Full picture: [system overview](docs/architecture/system-overview.md) ·
[agent loop](docs/architecture/agent-loop.md) ·
[observation model](docs/architecture/observation-model.md) ·
[verification & recovery](docs/architecture/verification-and-recovery.md).

## Why multiple languages

Each subsystem uses the best tool with a measurable reason
([ADR-001](docs/decisions/ADR-001-polyglot-architecture.md)):

| Subsystem | Language | Reason |
|---|---|---|
| Browser runtime, CDP, DOM/state, actions, verification | **Rust** | Performance, reliability, precise resource control |
| Planning, LLM orchestration, memory, providers, eval | **Python** | Ecosystem (LLM libs, Pydantic, eval harnesses), experimentation speed |
| Extension, trace viewer, browser-facing UI | **TypeScript** | It runs in the browser; nothing else does |
| Dev scripts, UI tooling | **Bun** | Only where it measurably beats Node |
| High-throughput services | **Go** | Only later, only with benchmarks justifying it |

Rule: **no language is added without a clear benefit**, and subsystem
interfaces stay language-independent. Details:
[language boundaries](docs/architecture/language-boundaries.md).

## Repository structure

```
browser-agent/
├── crates/            Rust workspace (browser-core, cdp, observation,
│                      element-registry, executor, verification, recovery,
│                      telemetry, python-bindings)
├── python/            Agent runtime (uv package, PyO3 bindings via maturin)
├── web/               Frontend/browser-facing components (later)
├── benchmarks/        Suites (synthetic, BrowserGym, …) + reports
├── tests/             Fixtures, browser, integration, long-horizon tests
├── examples/          Minimal usage examples
├── docs/              Architecture, benchmarks, development, ADRs, protocols
└── scripts/           Setup and maintenance helpers
```

## Development setup

Prerequisites: Rust stable (see `rust-toolchain.toml`), `uv`, Python ≥ 3.12,
a Chrome/Chromium binary, Node 22+ (for Pyright).

```sh
make setup     # install toolchains, create venv, build bindings
make build     # cargo build + maturin develop
make test      # cargo test + pytest
make lint      # clippy, fmt --check, ruff, pyright
make example   # run examples/basic_agent.py
```

Manual equivalent:

```sh
cargo build --workspace
cd python && uv sync --extra test && uv run pytest
```

## Benchmark-first philosophy

Benchmarks exist from the beginning
([evaluation plan](docs/benchmarks/evaluation-plan.md)). North-star metric:
**task success rate**, with steps, LLM calls, tokens, cost, latency, failure
and recovery rates tracked alongside. Do not claim an improvement without
measuring it.

## Roadmap

0. scaffold + research → 1. browser runtime → 2. observation + element
identity → 3. executor + verification → 4. first autonomous loop → 5. memory
+ progress → 6. recovery → 7. vision/code escape hatch → 8. provider
hardening → 9. benchmarks → 10. privacy/extension/procedural memory.
Each phase has a measurable gate: [roadmap](docs/development/roadmap.md).

## Contributing / security

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, commands, PR and ADR policy.
- [AGENTS.md](AGENTS.md) — mandatory reading for coding agents.
- [SECURITY.md](SECURITY.md) — scope and responsible disclosure.

License: MIT. See [LICENSE](LICENSE).
