# BROWSKI Rust Browser Foundation

BROWSKI is an open-source autonomous browser-agent runtime. This repository
contains its Rust browser foundation: persistent Chromium control, semantic
observation, stable element identity, typed actions, and deterministic
verification. Its Python package also contains a LangGraph workflow and a
shared System One decision interface with local Laya and optional TypeSafe Jev
adapters.

```python
from browser_agent import BrowserSession

async with BrowserSession.launch() as browser:
    await browser.navigate("https://example.com")
    snapshot = await browser.observe()
    print(snapshot.title)  # Example Domain
```

> **Status:** M0–M4 runtime foundations and M5 decision-provider contracts are
> implemented; the task-oriented CLI still awaits M6. Laya is the default
> local CPU provider, served separately at `http://127.0.0.1:8000`; Jev is
> optional and requires a TypeSafe API key.
> Adapter contract tests use fakes. Live model quality,
> calibration thresholds, latency, and cloud integration have not been
> measured. GPT-6 Luna is the planned System Two reasoning provider and is not
> implemented. The low-level `AgentRuntime` constructor still uses an
> in-memory saver for tests and injection; use its `open_sqlite` context
> manager for durable task checkpoints. CLI task orchestration remains planned
> until the reasoning provider is integrated.
> See the [roadmap](docs/development/roadmap.md) for milestone gates.

Install Jev's optional SDK from `python/` when cloud decisions are enabled:

```sh
uv sync --extra decisions-cloud
```

Run Laya separately with its local service setup, for example:

```sh
pip install "laya[serve]"
LAYA_HOST=127.0.0.1 LAYA_DEVICE=cpu laya-serve
```

`DecisionConfig` selects `laya` by default and also accepts `jev` or `adaptive`.
Provider-specific calibration, thresholds, timeouts, and the Laya endpoint are
configured independently. BROWSKI does not start Laya or download its weights
when a task runs.

## What "browser agent" means here

The planned runtime takes natural-language tasks and executes browser work
through LangGraph orchestration, bounded Laya/Jev decisions, and GPT-6 Luna
reasoning. This Rust repository supplies the browser-facing foundation; it
does not yet complete natural-language tasks autonomously.

## Why this project exists

The design keeps browser state, element identity, execution, and deterministic
verification in Rust. Agent orchestration and model decisions will remain in
the Python layer. Architecture claims are gated on reproducible benchmarks.

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

M0 scaffold, M1 persistent browser runtime, M2 observation + element identity,
M3 executor + verification, the M4 LangGraph runtime core, and M5
decision-provider contracts are implemented. Next gates are M6 adaptive Luna
reasoning and M7 memory/progress/recovery. See the
[roadmap](docs/development/roadmap.md) for gates and later optional milestones.

## Contributing / security

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, commands, PR and ADR policy.
- [AGENTS.md](AGENTS.md) — mandatory reading for coding agents.
- [SECURITY.md](SECURITY.md) — scope and responsible disclosure.

License: MIT. See [LICENSE](LICENSE).
