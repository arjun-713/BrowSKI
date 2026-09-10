# ADR-002: Browser-control architecture

Date: 2026-09-10 · Status: accepted (slice) · Revisit in: Milestone 1

## Context

The Rust core must launch Chromium, drive pages, observe state, and execute
actions. Candidates differ in control depth, maintenance risk, and fit with
the Rust-owns-the-browser rule.

## Options compared (checked against crates.io, 2026-09-10)

- **Direct CDP** (own minimal typed client over `tokio-tungstenite` +
  `serde_json`). Full protocol control, zero third-party browser deps, no
  abandonment risk — but we own multiplexing, session management, and type
  coverage.
- **`chromiumoxide` 0.9.x** (`mattsse/chromiumoxide`; generated
  `chromiumoxide_cdp` types). The most complete Rust CDP client: browser
  launch, targets, sessions, event streams, JS evaluation. Leading external
  candidate; cost is API surface area and tracking its release cadence.
- **`headless_chrome` 1.0.x** (`rust-headless-chrome`). Simpler API, maintained
  1.x line, good for “launch + evaluate + screenshot” — but thinner on
  multi-target/event-stream control than chromiumoxide.
- **`playwright-cdp` 0.3.x**. Young (0.3), single-maintainer shape; promising
  idea (CDP without a Playwright driver) but immature for a foundation.
- **Python Playwright as the core + CDP where needed**. Rejected for the core:
  it violates language ownership (browser transport would live in Python) and
  couples us to Playwright’s driver distribution. Playwright remains
  acceptable as a *benchmark/test harness* dependency, not the runtime.
- **WebDriver (e.g. `fantoccini`)**. Rejected: WebDriver lacks the CDP depth
  (targets, frames, AX, interception, events) the observation and
  verification designs require.

## Decision

- **Slice (v0.1): direct minimal CDP client** (`crates/cdp`): process launch,
  `/json/*` HTTP endpoints, one short-lived websocket per command batch,
  `Page.navigate` + `Runtime.evaluate` + readiness polling. Proven working
  against Chrome 152 (`cargo test -p browser-agent-core --test smoke`).
- **Milestone 1:** evaluate `chromiumoxide` 0.9.x behind the `cdp` crate’s
  interface (transport stays swappable) for persistent multiplexed sessions
  and event streams; fall back to hardening the direct client if the
  evaluation fails on stability, API churn, or binary-size/build grounds.
  `headless_chrome` is the alternate only if its event/target story improves.

## Consequences

- `crates/cdp` keeps a transport trait boundary so the client can be swapped
  without touching `browser-core` callers.
- No Playwright/WebDriver runtime dependency in the core, now or by default.
- This ADR is revisited in Milestone 1 with measurements, not opinions.

## M1 update (2026-09-10): benchmarked, custom transport kept

Comparison run on the same machine (local fixture server; custom = full
stress suite, chromiumoxide = feature-gated spike
`cargo test -p browser-agent-cdp --features transport-chromiumoxide
--test chromiumoxide_spike`, 20 navs / 10 tab cycles / 20 concurrent
evaluates — a workload subset, stated honestly):

| Dimension | Custom transport | chromiumoxide 0.9.1 |
|---|---|---|
| Sequential nav | p50 30ms, p95 40ms, p99 58ms (n=100) | p50 51ms, p95 146ms, p99 175ms (n=20) |
| Tab create/nav/close | p50 87ms, p95 103ms (n=100) | p50 79ms, p95 87ms (n=10) |
| Concurrent eval | 50/50 exact, p50 8.7ms | 20/20 exact, 22ms total |
| Reliability | 12/12 stress gates pass | spike workload passes |
| Extra transitive crates | 0 | ~28 (`cargo tree` delta 171 → 199) |
| Duplicate stacks | none | async-tungstenite 0.32 + reqwest 0.13 alongside our tokio-tungstenite + reqwest 0.12 |
| Protocol types | hand-rolled, only what we use (~650 lines) | generated ~60K lines (`chromiumoxide_cdp`) |
| Maintenance | ours to maintain | active: 0.9.1 (June 2026), owners mattsse + Sytten |

No decisive latency/reliability advantage either way on this workload; the
custom layer stays tiny and controllable with zero duplicate dependencies.
**Decision: keep the custom transport.** Re-evaluate at M2 if full typed
DOM/AX command coverage makes the generated types worth their weight — that
is the concrete condition, not a calendar date.

What was NOT compared (out of scope for the spike): frame-tree depth
handling, reconnect semantics, event latency under load, memory over
long sessions. A challenger must beat the custom transport on the full
stress suite, not the subset, to replace it.
