# Local debug sessions

BROWSKI can capture each task in a separate local JSONL file. Capture is
disabled by default. Enable it in the runtime's TOML configuration:

```toml
[debug]
enabled = true
directory = "/absolute/path/to/mango/debug-logs"
max_session_bytes = 16777216
max_sessions = 100
retention_days = 30
```

Use the BROWSKI implementation checkout for this path. Restart `browski serve`
after changing this configuration. Extension settings updates preserve this
section. Managed CLI tasks use the same capture configuration.

## What is recorded

Each run writes `debug-logs/<run_id>/events.jsonl`. Resume and confirmation
append to that run's file. Every record contains a schema version, timestamp,
sequence, run ID, runtime session ID, event name, optional step, and payload.

- `task.received`, `task.prompt`, `task.control`, and `task.result`: the task instruction,
  pause/resume/stop/approval controls, and final or interrupted status.
- `runtime.event`: the structured events used by the side-panel timeline.
- `task.error`: runtime exception class and up to 12 code locations (file
  basename, function and line). Raw exception messages, source lines and local
  variables are excluded because they can contain private page content.
- `provider.request`: provider, operation, model, effort, instructions,
  structured input, and output-schema metadata.
- `provider.response`: public structured/message output, token usage, and
  request latency, correlated with its request by `call_id`.
- `provider.error` and `provider.validation_failed`: safe error classifications.
- `decision.candidate_validation`: the proposed action, bounded candidate
  descriptions, candidate signatures, differing fields, and rejection reason.
- `browser.observation`, `decision.result`, `browser.action_started`,
  `browser.action_result`, `browser.verification`, and
  `browser.action_invalidated`: safe browser metadata and routing outcomes.

For “action outside the bounded candidate set,” inspect
`decision.candidate_validation`. A `signature_mismatch` includes comparison
fields such as `dy`, `clear`, or `target`. `action_binding_failed` indicates
that the proposed target could not be bound. Logging never authorizes a
rejected action.

```sh
find debug-logs -name events.jsonl -printf '%T@ %p\n' | sort -n
tail -f debug-logs/<run_id>/events.jsonl
jq 'select(.event == "decision.candidate_validation")' \
  debug-logs/<run_id>/events.jsonl
```

## Privacy and limits

This is sanitized diagnostic capture, not a raw HTTP dump. API keys, auth
headers, cookies, recognized secrets/PII, credential-field text, form-value
fields, browser-code scripts, hidden reasoning, and images are redacted or
omitted. Screenshot metadata may be recorded; screenshot bytes are never
written by this logger. Browser outcome records use the existing safe
checkpoint summaries. SDK errors are classified without persisting their
raw messages, which can echo private request content.

Strings containing recognized PII or token patterns are redacted in full.
Strings longer than 4,096 characters and deeply nested or large payloads are
bounded. These heuristics do not recognize every possible sensitive value:
ordinary task instructions and page text can still contain personal data.
Review logs before sharing them. Capture does not weaken provider privacy
mode or expose hidden model reasoning.

Directories are owner-only (`0700`); log files are owner-only (`0600`). The
repository ignores `debug-logs/`. A different configured directory must also
be excluded from Git before use. Cleanup is bounded and skips active runs,
symlinks, and directories containing other files. Defaults retain 100 sessions
and remove captures older than 30 days when opening a new run, subject to
bounded scanning and exclusions. Arbitrary unrelated files in the log root
can limit cleanup. Each run is capped at 16 MiB and emits
`debug_log_truncated` when full.

One runtime owns a run's capture file. Do not run multiple runtime processes
against the same run ID and capture directory. Storage failures emit a safe
warning and disable capture for that binding rather than breaking the task.
Past API responses cannot be recovered if capture was not enabled. SDK
failures before a public response is returned produce error metadata instead.

Disable capture with `enabled = false` and restart the service. Delete the
`debug-logs/` directory to remove stored captures after debugging.

## BROWSKI 2.0 managed engines

`browski run/task` and extension General/Fast tasks now use the same opt-in
capture binding. The result includes a `run_id`; the sidebar uses its existing
run identity. `engine.event` records the engine, model/provider, step, operation,
target ID, observed effect and inference timing. A provider failure is distinct
from a browser-operation failure. `task.result` records final status, verification,
steps, actions, generative calls, recoveries, provider errors and elapsed time;
it excludes final prose and browser content. The timeline shows these counters
in the final result. Existing raw provider request/response capture described
above belongs to Legacy; the Browser Use adapter does not capture hidden reasoning
or raw HTTP bodies.

Detailed Fast capture additionally needs `[traces] level = "detailed"` and
`[debug] enabled = true`. It records `fast.decision_input` and
`fast.decision_result`. Inputs are sanitized by the same bounded logger: field
values are redacted, long strings may be truncated, and URL query/fragment data
is removed. A replay compares the saved sanitized state, which may differ from
the original page state. It never replays a browser action.

When Jev credentials become available, export one input and compare providers:

```sh
jq -c 'select(.event == "fast.decision_input") | .payload' \
  debug-logs/RUN_ID/events.jsonl | head -n 1 > /tmp/browski-decision.json
browski compare-fast /tmp/browski-decision.json \
  --checkpoint /absolute/path/to/laya-browser-v19s --allow-paid-api
```

`compare-fast` needs `TYPESAFE_API_KEY` and explicit paid permission before
reading the input or loading Laya. It validates the contract, sends the same
request to both adapters, reports normalized choices/timings, and executes zero
browser actions. Malformed or excessively large inputs are refused. Live Jev
comparison is unverified until real credentials exist; offline tests cover wiring.

General inference timing covers the complete HTTP response. Laya's reported
inference timing excludes checkpoint/tokenizer loading. Task elapsed time includes
startup, observation and cleanup; do not compare these different timing scopes
as though they were equivalent benchmarks.
