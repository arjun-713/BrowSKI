# Luna prompt caching and usage observability

GPT-6 Luna uses the Responses API. OpenAI automatically selects cache
breakpoints for supported models; the adapter uses one explicit breakpoint at
the end of BROWSKI's fixed developer instructions for GPT-5.6 and GPT-6 model
IDs. The request sets `prompt_cache_options` to explicit mode with the supported
`30m` TTL. Explicit mode disables the implicit breakpoint on the latest input,
so changing task and page context is not written as a new cache prefix on every
call. Models outside those named families retain the existing instructions and
input request shape.

The fixed instructions are sent as a developer message. The serialized
`ReasoningContext` is sent separately as user input and continues to carry the
user task, runtime memory, semantic observation, and visual observation in
their own fields. The cache boundary is before that variable context. No
`prompt_cache_key` is required for cache hits, and the adapter does not derive
one from user, task, run, page, or other request data.

Caching only reuses prompt processing. Luna still receives current context on
every request, and cache contents never authorize an action or replace current
browser observation and Rust verification. The adapter does not add filler to
reach the API's 1,024-token minimum prefix. If the fixed prefix is too short for
a model to cache, telemetry will show no cached tokens.

## Reported usage

Luna telemetry records values returned by the provider when present:

- total input and output tokens;
- cached input tokens and cache-write input tokens;
- non-cached input tokens, derived only when both input and cached counts are
  valid and consistent;
- output reasoning tokens.

Missing or invalid counts remain unknown (`None`); they are not recorded as
zero. Opt-in debug capture includes the same usage breakdown, while excluding
hidden reasoning and transport secrets. Provider telemetry does not store
prompt text or use a cross-user cache key.

The adapter does not estimate currency cost. Cached reads are charged at the
model's applicable cached-input rate and cache writes at its applicable
cache-write rate, so a cost estimate requires current model-specific rates and
all relevant usage categories. The usage records are sufficient to make that
calculation in a later analysis without presenting an unsupported savings
claim.

To evaluate caching, run the same controlled Luna workload repeatedly with
debug capture enabled and compare provider-reported cached, cache-write, and
non-cached input counts alongside task success, call count, latency, and total
tokens. Separate cold prefixes from later requests. A reported cached-token
count demonstrates a cache read for that request; it does not by itself prove
lower end-to-end cost or improved task success.

## Controlled probe on 2026-10-15

A two-call local synthetic Luna probe exercised the same fixed instruction
prefix with a changed task and page state. Both calls returned successfully;
the synthetic decisions did not execute browser actions.

| Call | Input tokens | Cache writes | Cached reads | Non-cached input | Output tokens | Reasoning tokens | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Cold prefix | 2,466 | 2,112 | 0 | 2,466 | 97 | 16 | 7,114 ms |
| Follow-up | 2,466 | 0 | 2,112 | 354 | 79 | 0 | 6,227 ms |

The follow-up confirms a 2,112-token cache read for this prefix. This is one
small fixture pair: it does not establish a cost reduction, latency improvement,
or task-reliability result. The raw records are local-only artifacts under the
ignored `debug-logs/` directory on the machine that ran the probe; they are not
included in this repository:

- `debug-logs/task-mix-20261015/cache-probe/results.jsonl`
- `debug-logs/task-mix-20261015/cache-probe-follow-up/results.jsonl`
