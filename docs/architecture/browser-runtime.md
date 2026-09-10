# Browser runtime (Milestone 1)

One persistent browser-level CDP connection per session, owned end to end by
the Rust core. The Python agent treats `BrowserSession` as dependable
infrastructure: commands correlate, events arrive typed, crashes are states.

## Transport

`crates/cdp/src/transport.rs` — `PersistentTransport`. Rule: **only the
transport owns the socket.**

```text
                   CDP WebSocket (browser endpoint)
                       │
              ┌────────┴────────┐
              ▼                 ▼
          Reader task        Writer task
              │                 ▲
              │                 │
      CDP messages          Command queue (mpsc, 256)
              │
       ┌──────┴──────┐
       ▼             ▼
 Responses         Events
       │             │
 pending map      broadcast bus (1024)
 (id → oneshot)     │
       │        subscribers
       ▼             ▼
 awaiting calls   session pump
```

- Command correlation: `AtomicU64` ids; reader resolves `{"id": N, ...}`
  against the pending map; anything without an `id` is an event.
- Timeouts remove the pending entry — a slow browser can never deadlock the
  transport (`command_timeout`, default 30s; `pending_commands()` is the
  leak watchdog).
- Reader/writer death fails all pending work with `ConnectionLost` and
  broadcasts it; `close()` is idempotent, `Drop` aborts tasks.
- Malformed frames and unknown event methods never kill the reader
  (parse-and-continue; unknown methods become `CdpEvent::Unknown`).
- Wire log: `BROWSER_AGENT_WIRE=1` dumps truncated frames to stderr
  (diagnostics only, never in hot paths unconditionally).

## Identity

`Browser → Target → Tab → Frame`, with distinct newtypes
(`observation`, re-exported by `cdp`): `TargetId`, `TabId`, `CdpSessionId`,
`FrameId`, `ExecutionContextId`. A `Tab` is a page target plus its flattened
session; `TabRegistry` (`browser-core/src/model.rs`) is updated only from
transport events and confirmed command results.

Attach strategy (`BrowserSession::initialize`): the pump spawns first, then
`setDiscoverTargets` + `setAutoAttach(flatten)`; existing page targets are
adopted via their `attachedToTarget` events with a bounded wait, falling back
to explicit `Target.attachToTarget` (synchronous session id). Startup can
neither miss nor double-bind: adoption is idempotent and latest-wins.

## Events

`CdpEvent` (protocol) → session pump → `BrowserEvent` (tab-scoped):
`NavigationStarted/Completed`, `FrameAttached/Detached`,
`TargetCreated/Destroyed`, `DialogOpened`, `DownloadStarted/Completed`,
`PageCrashed`, `ConnectionLost`. Note the wire-level trap this design
survived: `attachedToTarget`/`detachedFromTarget` carry `sessionId` inside
`params`, unlike session-scoped events where it rides the envelope.

## Errors

`BrowserRuntimeError`: `BrowserExited`, `ConnectionLost`, `TargetClosed`,
`FrameDetached`, `CommandTimeout`, `ProtocolError`, `LaunchFailure`,
`SessionClosed`, `NoActiveTab`, `NavigationFailed` (+ transparent `Cdp`).
`is_terminal()` decides run termination. Chrome error pages
(`chrome-error://`) fail navigation immediately instead of burning the full
timeout. Low-level recovery maps these onto its `FailureKind`s (terminal
connection states escalate with evidence).

## Concurrency rules (normative)

1. Only `cdp::transport` touches the socket. Everything else uses typed
   commands and the event bus.
2. Never hold a lock guard across an `.await` — and in particular, never
   `if let` directly on `tabs.read().await…` when the body locks again:
   scrutinee temporaries live through the body and self-deadlock `write()`.
   Resolve to an owned value in a `let` first, then branch. (This exact bug
   froze the M1 runtime; the stress suite now guards the behavior.)
3. `std::sync::Mutex` in async code only for microsecond-critical sections,
   never held across `.await`.
4. Broadcast subscribers must tolerate `Lagged` (slow consumers drop, the
   pump never blocks).

## What M1 deliberately omits

Live download end-to-end (events parsed + translated, behavior control lands
with the M3 executor), full AX/DOM observation (M2), autonomous loop (M4).
