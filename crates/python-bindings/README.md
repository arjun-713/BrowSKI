# python-bindings

PyO3/maturin interface exposing the stable high-level Rust API to Python as
`browser_agent._core` (`PyBrowserSession`, `core_version`).

## May

- Wrap `BrowserSession::launch/navigate/observe/close` synchronously (the
  Python side adapts to `asyncio` via `to_thread`).

## May NOT

- Expose raw CDP handles, websockets, or other implementation details.
- Grow new APIs without a `docs/protocols/versioning.md` entry when the
  change affects serialized contracts or the binding surface.
