.PHONY: setup build test lint format bindings example benchmark-smoke clean

setup:
	./scripts/setup.sh

build:
	cargo build --workspace
	uv sync --project python --extra dev
	uv run --project python maturin develop --manifest-path crates/python-bindings/Cargo.toml
	cd extension && npm ci && npm run build

test:
	cargo test --workspace
	cd python && uv run pytest

lint:
	cargo fmt --all -- --check
	cargo clippy --workspace --all-targets -- -D warnings
	cd python && uv run ruff check .
	cd python && uv run ruff format --check .
	cd python && (uv run --extra dev pyright || npx --yes pyright .)

format:
	cargo fmt --all
	cd python && uv run ruff check --fix . || true
	cd python && uv run ruff format .

bindings:
	cd python && uv run maturin develop

example:
	cd python && uv run python ../examples/basic_agent.py

benchmark-smoke:
	cargo test -p browser-agent-core --test action_latency -- --ignored --nocapture

clean:
	cargo clean
	rm -rf python/.venv
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
