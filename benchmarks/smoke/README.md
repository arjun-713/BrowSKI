# Local Luna smoke harness

`run_live.py` runs bounded browser tasks against the synthetic pages in
`tests/fixtures/smoke/`. It launches headless Chromium, uses the configured
Luna provider, and independently checks task status, expected visible
viewport text, expected semantic element values, step and provider-call
bounds, and tab destinations. The laptop shortlist is local browser state;
the harness does not contact a retailer or submit an order.

## Live run

The harness is opt-in. Without `--confirm-live-api`, the CLI exits before it
loads the runtime configuration or starts the fixture server, so it cannot
make a provider request. With the flag, it requires an existing configured
OpenAI credential and may incur API usage charges. It does not print or save
the credential.

Run all current cases with an existing configured key:

```sh
UV_CACHE_DIR=/tmp/mango-smoke-uv uv run --project python \
  python benchmarks/smoke/run_live.py --confirm-live-api
```

Select one or more cases by repeating `--case`:

```sh
UV_CACHE_DIR=/tmp/mango-smoke-uv uv run --project python \
  python benchmarks/smoke/run_live.py \
  --confirm-live-api \
  --case short-picker \
  --case medium-preferences \
  --artifacts debug-logs/live-task-smoke-2026-10-12
```

Use a new artifact directory for each run. The runner creates a random local
port and records the resulting URLs in its manifest, so the manifest checksum
is a run identity, not a cross-run checksum of prompt wording. The manifest
and SHA-256 file are written before the first case starts. They record the
selected prompts, expected evidence, model, reasoning effort, and task bounds.
Retain them with the case JSON, final snapshots, provider debug events, and
summary when comparing runs.

Each case has a 120-second wall-time cap and explicit step and provider-call
bounds. The output distinguishes runtime `llm_calls` from raw calls counted
from `provider.request` / `provider.response` debug events. It records
per-call provider latency and usage plus Rust execution phase timings from
`browser.action_result`. Run elapsed time includes browser startup and local
fixture interaction, so it is not comparable to summed provider latency.

## Local checks without a provider

These tests use deterministic in-process providers and local Chromium only;
they do not contact the Luna API:

```sh
UV_CACHE_DIR=/tmp/mango-smoke-uv uv run --project python \
  pytest -q python/tests/test_smoke_task_integration.py
```

The viewport assertion helper is also exercised with visible, partially
visible, hidden, and offscreen semantic elements. It uses element visibility
and viewport-intersecting geometry; it deliberately ignores the broad text
excerpt and text-block fields for independent visible-goal checks.

## Artifact and comparison notes

`debug-logs/` is ignored by Git. Failed attempts and their event logs are
useful evidence; keep them when adding a later rerun rather than replacing the
earlier record. The October 9 baseline report and its original artifacts are
historical records. In particular, old task-level call counters and
`ActionStarted`/`ActionCompleted` pairings are not raw provider counts or
Rust action timings. Older broad text matching also did not independently
prove that a goal was in the viewport. Use the current raw provider events,
`browser.action_result` timings, final snapshot, and recorded checker fields
for new comparisons.

The frozen four-prompt rerun manifest is retained separately under
`debug-logs/original-smoke-rerun-20261012/`. Its SHA-256 is documented in
[`live-agent-repair-2026-10-12.md`](../../docs/development/live-agent-repair-2026-10-12.md).
New fixture cases exercise specific local workflows; passing them does not
establish a general browser-task success rate or compatibility with public
retailer sites.
