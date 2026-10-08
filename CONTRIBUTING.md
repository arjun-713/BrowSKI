# Contributing

## Setup

Prerequisites:

- Rust stable toolchain (`rust-toolchain.toml` pins `stable` + `rustfmt`/`clippy`).
- `uv` (Python package management) and Python ≥ 3.12.
- A Chrome or Chromium binary (`CHROME_PATH` env var overrides discovery).
- Node 22+ and npm (extension tooling and Pyright).

```sh
make setup     # verify toolchains, create python/.venv, build bindings
```

## Building

```sh
make build     # cargo build --workspace + maturin develop (python/)
```

Manual:

```sh
cargo build --workspace
cd python && uv sync --extra test
```

## Running tests

```sh
make test      # cargo test --workspace + pytest (python/)
```

- Rust: `cargo test --workspace` (includes live-Chromium smoke test
  `crates/browser-core/tests/smoke.rs`; needs Chrome + network).
- Python: `cd python && uv run pytest` (includes `test_session_smoke.py`).
- Extension: `cd extension && npm ci && npm run check`.
- Real extension smoke: install Playwright Chromium from `python/` with
  `uv run playwright install chromium`, build the extension, then run
  `make test-extension-e2e`. Native Messaging, Chrome debugger APIs, Rust
  actions, verification and the graph are real; provider responses are local
  fixtures and no model API is called.

## Lint / type-check / format

```sh
make lint      # cargo fmt --check, cargo clippy, ruff check, ruff format --check, pyright
make format    # cargo fmt + ruff format (write mode)
```

Manual:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cd python && uv run ruff check . && uv run ruff format --check .
cd python && uv run pyright
```

## PR expectations

- Keep changes scoped; one architectural concern per PR.
- Update/add tests for behavior changes (unit + browser smoke where relevant).
- Run `make test` and `make lint` before opening the PR; paste results.
- Public API or serialized-schema changes must note compatibility per
  `docs/protocols/versioning.md`.
- Behavior or performance claims need measurements per
  `docs/benchmarks/evaluation-plan.md` (or state explicitly that none exist yet).

## ADR policy

Write an ADR in `docs/decisions/` (`ADR-NNN-<slug>.md`, increment the number)
when you change shared contracts non-trivially, add/remove a language or
major dependency, choose browser-control machinery, or alter cross-language
APIs. Read `docs/decisions/ADR-001-polyglot-architecture.md` and
`docs/decisions/ADR-002-browser-control.md` first.

## Benchmark requirements

See `docs/benchmarks/evaluation-plan.md`. Track task success plus steps, LLM
calls, tokens, cost, latency, failure/verification/recovery/stagnation rates.
Do not claim an improvement without measuring it.
