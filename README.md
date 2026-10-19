# BROWSKI — Browser Agent Runtime

BROWSKI turns natural-language tasks into browser actions and checks the resulting
browser state. **BROWSKI 2.0 is in migration**, with working navigation and bounded
field slices;
it is not yet a general production-ready replacement for the Legacy runtime.

- **Fast** defaults to the released browser-tuned **Laya** checkpoint on CPU.
  It selects bounded operations/targets; it is not a text generator. Current
  execution supports web links and approved quoted-literal text, native date and
  single-select fields and one approved named transition in the
  sidebar. Final page checks and every requested field stage must be verified.
- **General** wraps the official **Browser Use Agent**, using a separately
  configured OpenAI text model. The sidebar supports navigation/read and a
  bounded approved click/text-entry slice; broader workflows remain in migration.
- **Jev** is an optional hosted Fast provider behind the same versioned decision
  contract. Offline contracts and switching pass; live Jev is unverified because
  no credentials are available. No retraining is needed to change adapters.
- The WXT/React extension remains the product UI. General/Fast open an isolated
  task-owned Chrome profile; selected source tabs do not transfer authentication.
  Fast can open supporting tabs through native links and select owned HTTP tabs
  on the same host. General also has a verified owned-tab switch tool.
- Rust/CDP, Luna and LangGraph remain available under an explicit **Legacy**
  configuration for rollback. Their broader forms/tabs/checkpoint capabilities
  have not all migrated and must not be attributed to the new engines.

Paid inference is **off by default**. An API key alone cannot authorize it.
Only Laya runs locally on the current development machine; local generative
models are disabled. General/OpenAI or Jev requires explicit provider selection,
credentials, compatible privacy mode and paid permission. There is no paid fallback.

The actual first-look local navigation run completed **4/4** frozen tasks through
the extension using CPU Laya, including a three-click workflow, with **0 false
successes** against the fixture criteria and **0 generative calls**. This is a
small controlled sample, not a public-web reliability claim. See the
[evaluation plan and results](docs/benchmarks/evaluation-plan.md),
[canonical architecture](ARCHITECTURE_PLAN.md), and
[migration checkpoint](docs/architecture/migration-status.md) for exact scope.

## Install and start the migration runtime

The existing source installer builds the base runtime/bindings and extension.
The new engines and CPU model are optional extras, prepared explicitly afterward.
From the repository root:

```sh
./scripts/install.sh --preflight
./scripts/install.sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --project python --extra dev --extra engines --extra laya-cpu
python/.venv/bin/browski prepare-laya --directory "$PWD/.browser-data/laya-browser-v19s"
python/.venv/bin/browski doctor
python/.venv/bin/browski serve
```

The checkpoint is about 644 MB plus its tokenizer and CPU inference dependencies.
No GPU, model training, Jev key or paid inference is required for Fast/Laya.
This checkout is verified on Linux x86_64 with Google Chrome. Keep the prepared
checkpoint path absolute in Settings when starting the service from another
working directory. Doctor never runs inference or contacts a hosted provider.

Load `extension/.output/chrome-mv3` in `chrome://extensions` and register its
Native Messaging host as described in [installation](docs/user/install.md).
Open the side panel and connect. Fast/Laya can start from a link in the task or
an explicit starting page. It does **not** require attaching a Legacy source tab.
Use the optional expected URL/heading checks for independently verified navigation;
without a supported outcome check, a model's DONE is reported as unverified.
Pause/resume/stop and progress/results use the existing local bridge.

General needs generative inference: select OpenAI and permit paid API calls in
Settings before choosing it. Keys belong in the OS keyring or runtime environment,
never task text, TOML or logs. The existing key UI remains available; storing a
key does not enable paid access. In the sidebar, each General click or text entry
requires approval. Text must appear quoted in the task, such as `Type "Ada" into
Name`; a fresh field read verifies typing. Denial, Stop, expiry or a changed page
blocks the pending action. CLI tools stay read-only without an approval sink.
This controlled form integration has offline model fixtures, not live General
form-accuracy evidence. Legacy's approval path remains intact.

Fast reuses the existing bounded field grammar, for example `set "Full name" to
"Alex Demo"; fill "City" with "Pune"`. Quote both the observed field label and its
exact value. Laya/Jev choose the target; code supplies the literal and checks the
live value and native validity. For example, `set "Departure" to "2026-11-03";
set "Color" to "Blue"` supports a native date and a uniquely identified dropdown
option. Dates require valid YYYY-MM-DD within the control's constraints. Custom
widgets and multiple selection are unsupported. Missing/ambiguous fields cannot
be skipped for completion, including a field removed after an earlier action.
To submit, append an explicit named action such as `click "Save demo record"`.
It becomes eligible after all requested fields are verified, requires its own
approval and executes once. Supply a final URL/heading that does not already
match; fresh receipt checks decide completion. For a GET receipt, expected query
values are checked exactly. Arbitrary button sequences, source transfer and
file tools remain in migration. Task-owned browsers close when
the task finishes, so this field-filling gate does not preserve a form for later
manual work or establish durable session support.

The [configuration guide](docs/user/configuration.md) contains current engine
settings and explicitly labelled Legacy options. [Debugging](docs/user/debugging.md)
explains safe capture, provider/model timing, result counters and saved-input
comparison. Use `browski run/task` for configured engines, `browski general/fast`
for bounded explicit commands, and `browski --help` for options.

## Current architecture

```text
Extension / CLI
      |
Authenticated local lifecycle + engine policy + events
      |                           |
General: Browser Use Agent     Fast: bounded observation/action loop
      |                           |
OpenAI (explicit opt-in)       Laya CPU / optional hosted Jev
      |                           |
      +---- task-owned Browser Use browser mechanics ----+
                              |
                    isolated Chrome + fresh verification
```

General/Fast do not run inside the Legacy LangGraph or Rust executor. Python owns
new orchestration/adapters, Browser Use supplies browser mechanics, TypeScript
owns the UI/transport, and Rust retains Legacy mechanics. One controller owns a
managed task profile. [ADR-022](docs/decisions/ADR-022-local-first-engine-migration.md) and
[ADR-023](docs/decisions/ADR-023-product-engine-selection.md) explain the migration;
[ADR-024](docs/decisions/ADR-024-fast-candidate-destinations.md) versions destination
grounding; [ADR-027](docs/decisions/ADR-027-native-field-verification.md) explains native
control verification and bounded rereads. No additional orchestration framework
or cloud browser is required.
[ADR-029](docs/decisions/ADR-029-fast-form-workflow.md) describes the form-stage
checkpoint and independent receipt verification.

The active plan is [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md).
[CODE_QUALITY.md](CODE_QUALITY.md) and [AGENTS.md](AGENTS.md) govern development.
Legacy architecture docs and older evaluations remain historical references;
the earlier 16/18 development and 0/6 holdout study does not measure this runtime.

## Repository structure

```
BROWSKI/
├── crates/            Rust workspace (browser-core, cdp, observation,
│                      element-registry, executor, verification, recovery,
│                      telemetry, browser-code, python-bindings)
├── python/            Agent runtime (uv package, PyO3 bindings via maturin)
├── extension/         WXT/React MV3 side panel and browser transport
├── web/               Reserved product tooling; no second browser agent
├── benchmarks/        Suites (synthetic, BrowserGym, …) + reports
├── tests/             Fixtures, browser, integration, long-horizon tests
├── examples/          Minimal usage examples
├── docs/              Architecture, benchmarks, development, ADRs, protocols
└── scripts/           Linux source install and local release preparation
```

## Development setup

Prerequisites: Rust stable (Legacy bindings), uv, Python 3.12+, Chrome, and
Node 22+ for the extension/Pyright. After preparing the engine extras above:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 make test
UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 make lint
npm run check --prefix extension
PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" UV_CACHE_DIR="$PWD/.cache/uv" UV_NO_SYNC=1 make test-extension-e2e
```

Packaged tests need the matching Playwright Chromium installed in the configured
browser cache. Keep `UV_NO_SYNC=1` for these checks so base dev sync does not remove
optional engine/model extras. The latest full Python gate passes; the aggregate
Rust 100-cycle tab stress run currently stalls while its isolated case passes.
The checkpoint records that unresolved gate. Do not silently skip it or remove
Legacy because of it.

## Benchmark-first philosophy

Benchmarks exist from the beginning
([evaluation plan](docs/benchmarks/evaluation-plan.md)). North-star metric:
**task success rate**, with steps, LLM calls, tokens, cost, latency, failure
and recovery rates tracked alongside. Do not claim an improvement without
measuring it.

## Roadmap

The migration checkpoint distinguishes implemented, partial and pending phases.
Broader forms, custom controls, source-to-field transfer, authenticated sessions, long workflows and
resumability still need replacement evidence. Keep Legacy until those gates pass.
Task success is the primary metric; do not trade away verification for speed or
claim production readiness from a few fixture tasks.

## Contributing / security

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, commands, PR and ADR policy.
- [AGENTS.md](AGENTS.md) — mandatory reading for coding agents.
- [SECURITY.md](SECURITY.md) — scope and responsible disclosure.

License: MIT. See [LICENSE](LICENSE).
