# browser-core

Browser runtime: `BrowserSession` lifecycle, tab/frame registry, typed event
bus, first-class runtime errors.

## API

`launch / connect_to / close · tabs / active_tab / new_tab / close_tab /
activate_tab · navigate / navigate_tab · observe / observe_tab · execute /
handle_dialog · events / reconnect · is_live / pending_commands /
browser_pid / generation`

## May

- Launch/own the Chromium process (via `cdp`) or attach to an external one.
- Maintain the `TabRegistry` from transport events + confirmed results.
- Translate `CdpEvent`s into tab-scoped `BrowserEvent`s.
- Fail terminally and deterministically (`BrowserRuntimeError`,
  `is_terminal()`); fast-fail Chrome error pages.

## May NOT

- Call any LLM or import provider logic.
- Perform agent planning, memory, or strategy decisions.
- Expose raw CDP sockets (see `python-bindings` for the stable surface).

Browser state is never trusted indefinitely: `generation` increments on
navigation, and the registry is rebuilt from events rather than cached
forever. Stress gates: `tests/stress_runtime.rs`.
