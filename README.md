# BROWSKI — Open-Source Autonomous Browser Agent Runtime

BROWSKI operates a browser from natural-language tasks. Rust owns browser
observation, stable element identity, typed actions, and deterministic
verification. Python owns LangGraph orchestration, bounded memory and
recovery, and GPT-6 Luna reasoning. The Manifest V3 side-panel extension is
being productized as a UI and browser-session attachment layer; it is not a
second agent.

```python
from browser_agent import BrowserSession

async with BrowserSession.launch() as browser:
    await browser.navigate("https://example.com")
    snapshot = await browser.observe()
    print(snapshot.title)  # Example Domain
```

> **Status:** The managed Chromium runtime, semantic observation, executor,
> LangGraph workflow, persistence, progress, and recovery are implemented.
> GPT-6 Luna is the only provider allowed to produce executable decisions.
> Laya is shadow-only and Jev is disabled. The extension now has an
> authenticated Native Messaging bridge, attached-tab Rust transport, task
> dispatch, trace events, and confirmation handling. The complete extension
> driven demo and browser E2E flow have not yet been validated. Opt-in vision
> routing is available for explicit visual tasks; screenshot redaction,
> browser-code execution, complete privacy controls, and a supported installer
> remain incomplete. See the [roadmap](docs/development/roadmap.md).

For local development setup and extension loading, see
[installation](docs/user/install.md) and [extension setup](docs/user/extension.md).
Provider policy, secret handling, and privacy modes are described in
[configuration](docs/user/configuration.md) and [privacy](docs/user/privacy.md).

Run a managed-browser task with Luna:

```sh
cd python
uv sync --extra dev
OPENAI_API_KEY=... uv run browski run "Inspect the jobs page" \
  --start-url http://127.0.0.1:8080/jobs
```

Luna calls require a configured key and may incur API charges. The task command
writes LangGraph checkpoints to `browski-checkpoints.sqlite` by default. Use
`browski doctor` to inspect local prerequisites and `browski config` to review
effective non-secret settings; neither command calls OpenAI. Use
`browski runs list` to inspect safe run metadata and `browski runs clean` to
preview old checkpoint cleanup. Cleanup deletes nothing until `--apply` is
passed. Running records are protected unless you explicitly use
`--include-running` after verifying the runtime has stopped. Use
`browski --help` for the supported command options.

`browski serve` runs the authenticated local extension runtime. Attach a tab in
the side panel before submitting a task. The attached-browser task path uses
the shared Rust browser core and Python LangGraph runtime; it has not yet
passed the full local demo and extension E2E acceptance flow.

## Why this project exists

The design keeps browser state, element identity, execution, and deterministic
verification in Rust. Python owns LangGraph orchestration and GPT-6 Luna
decisions, with Laya available only as a non-executing shadow provider.
Architecture claims are gated on reproducible benchmarks.

## High-level architecture

```
USER TASK
   |
   v
LANGGRAPH (Python state, bounded memory, progress, recovery)
   |
   +--> GPT-6 Luna through the ComplexityGate (active decision path)
   +--> Laya shadow comparison (optional; cannot choose executable actions)
   |
   v
RUST BROWSER CORE (CDP, semantic observation, stable refs, executor,
                   deterministic verification)
   |
   v
CHROMIUM
```

Optional on-demand vision can supplement semantic observation for explicit
visual tasks when DOM, accessibility, and layout do not expose the needed
information. A restricted browser-code tool remains future work. Semantic
observation remains primary.

Full picture: [system overview](docs/architecture/system-overview.md) ·
[agent loop](docs/architecture/agent-loop.md) ·
[observation model](docs/architecture/observation-model.md) ·
[verification & recovery](docs/architecture/verification-and-recovery.md).

The [architecture plan](ARCHITECTURE_PLAN.md) governs design and milestones;
[CODE_QUALITY.md](CODE_QUALITY.md) governs implementation quality.

## Why multiple languages

Each subsystem uses the best tool with a measurable reason
([ADR-001](docs/decisions/ADR-001-polyglot-architecture.md)):

| Subsystem | Language | Reason |
|---|---|---|
| Browser runtime, CDP, DOM/state, actions, verification | **Rust** | Performance, reliability, precise resource control |
| Planning, LLM orchestration, memory, providers, eval | **Python** | LangGraph, typed schemas, provider adapters, eval tooling, experimentation speed |
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
M3 executor + verification, M4 LangGraph runtime, M5 decision providers, M6
adaptive Luna reasoning, and M7 bounded memory/recovery are implemented. Live
provider behavior remains unverified. See the
[roadmap](docs/development/roadmap.md) for gates and later optional milestones.

## Contributing / security

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, commands, PR and ADR policy.
- [AGENTS.md](AGENTS.md) — mandatory reading for coding agents.
- [SECURITY.md](SECURITY.md) — scope and responsible disclosure.

License: MIT. See [LICENSE](LICENSE).
