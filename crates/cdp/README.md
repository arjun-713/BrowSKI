# cdp

Typed CDP access, transport, and protocol adapters. Owns everything
Chrome-specific: process launch, `/json/*` HTTP endpoints, the persistent
multiplexed websocket transport, and typed protocol events.

## Ownership rule

**Only `transport.rs` owns the socket.** Reader/writer tasks are the sole
code touching the WebSocket; all other subsystems command the browser through
`PersistentTransport` and listen on the `CdpEvent` broadcast bus.

## May

- Find/launch Chromium, manage the debug endpoint and temp profile.
- Multiplex commands with id correlation, timeouts, and pending-count
  watchdog; dispatch typed events; fail everything deterministically on
  disconnect.

## May NOT

- Reason about tasks, plans, or providers.
- Define agent-level schemas (those live in `observation` / `executor`).
- Hold a lock guard across `.await` (see `docs/architecture/browser-runtime.md`).

Design: `docs/architecture/browser-runtime.md`. Transport comparison:
`docs/decisions/ADR-002-browser-control.md` (M1 update) and the
feature-gated spike `tests/chromiumoxide_spike.rs` (comparison only — the
`transport-chromiumoxide` feature must never gain dependents).
Diagnostics: `BROWSER_AGENT_WIRE=1` dumps truncated CDP frames to stderr.
