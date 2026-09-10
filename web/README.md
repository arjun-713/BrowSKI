# web

Frontend and browser-facing components. **Intentionally empty in the
scaffold** — no React app is created until a concrete consumer (trace viewer,
developer UI, browser extension, JS SDK) needs it.

When created:

- Bun preferred for dev tooling where compatible; keep Node compatibility
  for distributed libraries.
- React + Vite (or equivalent) for UIs; WXT if a browser extension lands.
- Communicate with the agent runtime through public APIs/events — never link
  agent internals (see `docs/architecture/language-boundaries.md`).
