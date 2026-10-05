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

> **Status:** M0–M5 and the M7 memory/recovery core are implemented. M6 now
> includes a GPT-6 Luna Responses adapter, deterministic reasoning-effort gate,
> hybrid decision agent, and task CLI; its integration gates are still being
> validated. Fake-backed tests do not establish live provider quality,
> calibration, latency, or cloud reliability. Laya is the default and runs as a
> separately managed local CPU service at `http://127.0.0.1:8000`; live CPU
> inference has not been verified in this checkout. Jev is optional and requires
> a TypeSafe API key. See the
> [roadmap](docs/development/roadmap.md) for measured status.

Install Jev's optional SDK from `python/` when cloud decisions are enabled:

```sh
uv sync --extra decisions-cloud
```

Run Laya separately in its own Python environment. The upstream CPU setup is:

```sh
python3 -m venv .venv-laya
.venv-laya/bin/python -m pip install "laya[serve]"
LAYA_HOST=127.0.0.1 LAYA_DEVICE=cpu LAYA_MODELS=english \
  LAYA_PRELOAD=1 LAYA_THREADS=4 .venv-laya/bin/laya-serve
```

The first service start downloads the selected checkpoint if it is not already
cached. These commands follow the [upstream Laya HTTP server
setup](https://github.com/NandhaKishorM/laya/blob/main/docs/http-api.md); CPU
thread count should match the host. `DecisionConfig` selects `laya` by default
and also accepts `jev` or `adaptive`. Its `laya_endpoint` setting changes the
client URL; the CLI defaults to `http://127.0.0.1:8000`. Provider calibration,
thresholds, and timeouts are configured independently. BROWSKI does not install
Laya, download weights, or start its service when a task runs.

The `BROWSKI_LIVE_LAYA` and `BROWSKI_LAYA_ENDPOINT` environment variables are
read only by the opt-in live provider contract test; they do not configure the
normal CLI. Set them only when deliberately running that test against a local
service. The local HTTP adapter has fake-backed contract coverage; live CPU
inference has not been run or verified in this checkout.

Run a task with the local Laya service and optional Luna escalation:

```sh
cd python
uv sync --extra dev
OPENAI_API_KEY=... uv run browski run "Complete the application form" \
  --start-url http://127.0.0.1:8080/form --provider laya
```

The OpenAI key is used only if the bounded System One provider escalates to
Luna. `--provider` accepts `laya` (default), `jev`, or `adaptive`. The task
command writes LangGraph checkpoints to `browski-checkpoints.sqlite` by
default. The `agent` console command remains available as a compatibility
alias. Use `browski --help` for options.

## Why this project exists

The design keeps browser state, element identity, execution, and deterministic
verification in Rust. Python owns LangGraph orchestration, Laya/Jev bounded
System One decisions, GPT-6 Luna System Two reasoning, and adaptive effort.
Architecture claims are gated on reproducible benchmarks.

## High-level architecture

```
USER TASK
   |
   v
LANGGRAPH (Python state, bounded memory, progress, recovery)
   |
   +--> DecisionProvider: Laya local CPU (default) | Jev cloud (optional)
   +--> GPT-6 Luna through ComplexityGate when planning must escalate
   |
   v
RUST BROWSER CORE (CDP, semantic observation, stable refs, executor,
                   deterministic verification)
   |
   v
CHROMIUM
```

Optional future capability: screenshot/vision as a fallback sensor; it is not
the primary observation path.

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
M3 executor + verification, M4 LangGraph runtime, M5 decision providers, and
the M7 bounded memory/recovery core are implemented. M6 Luna integration is
under validation. See the
[roadmap](docs/development/roadmap.md) for gates and later optional milestones.

## Contributing / security

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, commands, PR and ADR policy.
- [AGENTS.md](AGENTS.md) — mandatory reading for coding agents.
- [SECURITY.md](SECURITY.md) — scope and responsible disclosure.

License: MIT. See [LICENSE](LICENSE).
