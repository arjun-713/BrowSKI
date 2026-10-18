# Extension execution path audit

**Scope:** Read-only audit of the current side-panel-to-attached-browser task
path. This report does not change production code or tests. Existing worktree
changes were preserved.

## Finding from the Step 0 retries

I inspected the ignored local event files directly:

- `debug-logs/96ff39f1-f265-4187-b040-aedbfaa370e1/events.jsonl`
- `debug-logs/c4adaf68-9466-4275-8114-837cd10551c4/events.jsonl`

The first run (`96ff39f1-...`, 2026-10-15 18:47:57 UTC) contains
`task.received`, `task.prompt`, `RunStarted` at step 0, `RunFailed` at step 0,
and `task.error` with type `RuntimeError`. It has no successful observation or
provider event. Its `task.error` is missing traceback frames, so by itself it
locates failure only before successful observation; it does not prove whether
observation was attempted.

The retry (`c4adaf68-...`, 2026-10-15 20:05:27 UTC / 2026-10-16 01:35 IST) has
the same graph pattern, and its `task.error` frames end at
`graph.py:239 observe_node -> session.py:105 observe -> asyncio.to_thread ->
threading.Thread.run`. This proves the first observed divergence is the first
Rust observation called through PyO3, before Luna or Laya. It does not identify
the underlying Rust/CDP command or error. No provider request, action, or
verification was reached on this retry.

The two logs also prove a correlation defect: for the retry,
`task.received.session_id` is `b227c4e8-3d9a-45ee-8a21-e616843d0e5c`, whereas
`task.prompt` and graph runtime events use
`98c51b5a-4d40-4f3d-b391-5d5b6c381fcf`. The earlier run shows the same shape
with `e5de0e33-...` versus `c00cde65-...`. The service binds `task.received`
to the browser attachment session; `AgentRuntime.run` binds its debug events to
the runtime object's own generated session ID. `run_id` remains consistent.
This mismatch weakens log correlation but does not explain the observer error.

No code-level root cause for the native observation failure is established by
this audit. The reported successful manual attach/observe pass means the
failure is not universal, but is not a controlled reproduction of the failing
browser/run state.

## Execution and ownership trace

| Boundary | Actual contract and owner | IDs, errors, timeout and cleanup |
| --- | --- | --- |
| React submit | `TaskComposer.submitTask` in `extension/components/TaskComposer.tsx:22-32` dispatches `{ type: "task.submit", task }`; UI refuses empty text, over-limit text, busy/read state, or non-startable session. | No request or run ID is created here. The composer clears when background dispatch returns without an error. That return means the message was handed to the Native Messaging port, not that a run or observation succeeded. |
| Panel state / background router | `useRuntimeConnection.dispatch` in `extension/entrypoints/panel/useRuntimeConnection.ts:65-95` sends a Chrome runtime message. `createPanelMessageHandler` in `extension/src/panel-router.ts:16-188` checks the sender and request shape, requires a ready protocol/session, trims and bounds task text, then sends `runtime.task.submit` with the current `sessionId`. | Panel errors return a snapshot plus string error. There is no per-submit request ID or wait for task result. `NativeHostController.sendNative` in `extension/src/native-host.ts:44-57` confirms a port was present and the frame passed the extension size check. |
| Extension-to-host | `NativeHostController` in `extension/src/native-host.ts` connects the named Native Messaging host, sends protocol/capability negotiation and forwards bounded envelopes. It receives runtime timeline/status/result envelopes and updates the panel snapshot. | Native Messaging caller origin is checked by the host; protocol versions, frame schemas, event IDs and payload bounds are validated. Host disconnect clears protocol readiness and detaches owned tabs. The extension handshake has a 10 s bound. |
| Local native host / service | The host relays framed JSON to the authenticated local Unix socket. `ExtensionBridgeService._handle_connection` in `python/src/browser_agent/extension/service.py:318-398` authenticates the service token, validates hello/capabilities, then serially handles host messages. | Auth/hello bounds are 3 s/5 s; idle message read bound is 300 s; writes are bounded to 5 s. Host/session closure cancels attachment/task work, closes the Rust browser session and clears task state. The transport carries no task-submit acknowledgment correlation ID. |
| Attachment / backend session | `browser.tab.attached` is handled in `python/src/browser_agent/extension/service.py:425-457`; it carries an attachment UUID, Chrome numeric `tabId`, and extension-created `sessionId`. `BrowserSession.attach_extension` in `python/src/browser_agent/session.py:58-88` passes opaque attachment/session/target metadata into PyO3. The Rust extension transport uses that session ID as its root command-routing identity; the extension maps it to an owned Chrome tab. | Chrome numeric tab IDs remain extension-side. Attachment and browser-session IDs are distinct. The browser core/runtime also has an internal session UUID; service timeline serialization at `service.py:718-722` overwrites runtime event `sessionId` with the attachment session ID. This is a naming/correlation ambiguity, separate from the proven debug-log mismatch above. |
| Task/run creation | `runtime.task.submit` handling in `service.py:469-498` validates submitted `sessionId`, rejects a running/suspended task, generates `run_id = uuid4()`, sets session status to running and starts `_run_attached_task`. `AgentRuntime.run(task, run_id=run_id)` resolves and validates that ID and uses it as the LangGraph thread/checkpoint ID. | `run_id` is stable from service creation through graph events/checkpoints. Debug `task.received` uses the attachment session ID; `AgentRuntime.run` binds its own runtime UUID. No `request_id` or `trace_id` is propagated; `step` is the graph step count, not a unique step identifier. |
| Graph startup / first observation | `AgentRuntime._run` in `python/src/browser_agent/agent/runtime.py:205-273` claims the run, emits `RunStarted` with step 0, then invokes the graph. `observe_node` in `python/src/browser_agent/agent/graph.py:235-243` directly awaits `browser.observe()`, saves/records a snapshot, then emits `ObservationCompleted`. | There is no `ObservationStarted` or observation-failure timeline event. If observe throws, no observation event is emitted; `_run` emits `RunFailed` at step 0, records safe run state, and rethrows. This explains the observed missing observation event. |
| Rust observation / Python binding | Python `BrowserSession.observe` in `python/src/browser_agent/session.py:130-132` runs `_core.PyBrowserSession.observe_json` in `asyncio.to_thread`, then validates returned JSON as `SemanticSnapshot`. PyO3 `observe_json` in `crates/python-bindings/src/lib.rs:167-176` calls Rust `BrowserSession::observe()` and maps its result through `map_err`. | `map_err` in `lib.rs:34-36` turns Rust errors into plain `PyRuntimeError` text; Python loses the typed Rust error variant at this boundary. The call is off the asyncio event-loop thread. No explicit Python observation timeout or cancellation token is applied to the blocking worker call. Caller cancellation does not stop a running `to_thread` operation; teardown is the eventual cleanup path. |
| Rust attached transport / extension proxy | Rust correlates commands with monotonically assigned integer request IDs and a pending oneshot map in `crates/cdp/src/extension.rs:135-200`; session identity is included in each backend command. Python validates attachment/session ownership and correlates `browski-{request_id}` in `python/src/browser_agent/extension/backend.py:570-621`. The extension validates attachment, session, negotiated method and owned tab in `extension/src/debugger-proxy.ts:45-110` before `chrome.debugger.sendCommand`. | Rust command timeout is configured to 30 s at the binding; Python waits 35 s; the debugger proxy limits pending commands to 8. Python's dispatch exception handler converts timeout/disconnect to a generic backend error. A Rust timeout removes its pending entry while Python may still wait up to five more seconds. This mismatch is a diagnostic risk, not established as the cause of the reported observation failure. |
| Provider / action / verification | The graph reaches decision/provider work only after `observe_node` returns a semantic snapshot. Luna is the active executable decision route; Laya is optional shadow only. Python validates decisions/candidates; Rust executes typed actions and verifies postconditions. | No provider request, action, or verification was reached in the retry. Therefore the task did not fail in decision parsing or Rust action execution on that run. |
| Progress / timeline / terminal result | Runtime events are serialized, then service rewrites `sessionId` to the attachment session ID and sends them to the extension. `RunFailed` is labeled “Task stopped without completion.” `_run_attached_task` in `service.py:667-749` catches ordinary exceptions and emits generic `runtime.task.result` failure text. | Runtime event sink has a 0.5 s bound and is disabled after a send exception. Timeline retains the last 200 events. On run errors, graph event and task-result/status are separate representations of the failed run, not two graph failures. Whether the screenshot's two failure rows are duplicate renderings or distinct events was not established here. |

## Concrete diagnostic gaps and lifecycle risks

1. **Failure kind is lost at two boundaries.** PyO3 flattens the Rust error
   into `RuntimeError` text. Then `_run_attached_task` catches the exception
   without recording its type/metadata and returns a generic result.
   `AgentRuntime.run` does record `task.error` metadata for an exception
   inside the run, but the traceback ends at the binding and does not name the
   Rust error variant. These gaps obscure the cause; they do not explain why
   `observe()` failed.

2. **Step 0 has no observation-start/failure timeline event.** A missing
   `ObservationCompleted` is consistent with an observation exception, but
   does not independently prove a call happened. The retry's traceback proves
   it did.

3. **Debug session identity is overloaded.** `task.received` uses the
   attachment session ID; runtime debug records use `AgentRuntime.session_id`;
   timeline serialization replaces that runtime ID with the attachment ID.
   Keep `run_id` stable, but represent attachment/browser session and Python
   runtime session as separately named fields before relying on `session_id`
   for cross-layer correlation.

4. **There is no end-to-end `request_id`, `step_id`, or `trace_id`.** Native
   envelope `eventId` is regenerated per message; CDP `requestId` is scoped to
   transport commands; graph `sequence` and `step` are different counters.
   The run ID is consistent through the service and graph, but the requested
   correlation tuple is not present across all layers.

5. **Task submit is fire-and-forget at the panel boundary.** The panel treats
   successful dispatch as the native port accepting a frame; the service later
   generates the run ID. This can clear user input before task initialization
   is proven. It was not implicated in these retries because both produced
   `RunStarted` and `task.error` records.

6. **Timeout and cancellation are layered rather than unified.** CDP waits
   are bounded, but the binding's `to_thread` call has no cancellation
   mechanism. Service teardown cancels the graph task and then closes browser
   and session resources. A Python task cancellation alone does not prove a
   Tokio operation stopped; confirm pending Rust commands and transport state.

7. **A timeline gap is not proof of a missing command.** To prove the root
   cause, correlate backend command, debugger response/error, Rust transport
   response, and native error variant for the same run and operation.

## Current first-divergence conclusion

For the 01:35 IST retry, the evidence establishes:

```text
TaskComposer submit
  → panel/background dispatch accepted
  → native service creates run and emits RunStarted
  → LangGraph calls the first observe node
  → BrowserSession.observe reaches PyO3 observe_json in a worker thread
  → RuntimeError propagates before a SemanticSnapshot is returned
  → LangGraph emits RunFailed at step 0
  → service emits generic runtime.task.result failure
```

The **first failing boundary identified by traceback evidence is Rust
observation through the Python binding**. The exact Rust/CDP operation and
root cause remain unproven. No provider or action was reached. The next proof
needed is the typed Rust `BrowserRuntimeError` / `CdpError` variant and failing
command/session correlation from the same run. Do not label stale sessions,
session-ID mismatch, Chrome capability failure, or a provider problem as the
root cause without that evidence.

## Regressions to add after the cause is fixed

- Reproduce the exact attached-mode observation failure with the same
  attachment lifecycle and assert its error kind reaches the service, debug
  log, and extension result without exposing sensitive browser content.
- Assert a successful attached observation emits a semantic snapshot and the
  graph does not call the provider before that snapshot exists.
- Assert failed observation is represented as an observation failure (or an
  equivalent typed failure), rather than only a step-0 terminal event.
- Exercise stale attachment, browser-session mismatch, debugger command error,
  target closure, cancellation during observation, and reconnect separately;
  each should fail closed with a distinct safe category and clean pending
  commands/owned browser state.
- Keep the managed-browser observation path passing to show the fix is
  specific to, or safe across, the shared observer boundary.

These are proposed regressions. This audit did not implement or run them.

## Evidence limit

The checkout already had user changes in the extension UI and
`python/tests/extension/test_browser_e2e.py`; they were preserved. This report
is based on source inspection and the two ignored local event files. It is not
a fresh extension run or a reproduction of the failure. It does not establish
whether CLI attached mode or real extension attached mode is the
differentiating cause, and does not reassess the 24-task suite. The latest
16/24 corpus result was provided by the coordinating agent; it is a separate
baseline from the historical 18/24 claim.
