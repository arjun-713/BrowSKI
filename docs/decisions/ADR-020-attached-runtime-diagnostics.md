# ADR-020: Typed failures and authenticated attached-runtime diagnostics

Status: Active

Date: 2026-10-16

## Context

Two real extension runs terminated on the first Rust observation, before any
provider call. The PyO3 mapper retained only arbitrary exception text, which
the safe debug recorder intentionally excludes. Doctor inspected endpoint files
without proving a live extension, a CDP command round-trip or semantic
observation. A diagnostic client must not displace the single real extension
or invalidate its owned session.

A controlled attached-browser reproduction found that `DOM.getDocument`
returned a 15,571-byte response nested 171 levels deep. `serde_json`'s default
128-level recursion limit rejected the valid response; the reader then reported
only `ConnectionLost` to the pending command.

## Decision

- Keep one Rust semantic browser engine and the existing authenticated
  owner-only Unix socket / Native Messaging bridge.
- Authenticate every client before allowing it to claim the extension slot.
  A strict versioned `runtime.diagnostics` request branches before that claim.
  Diagnostics neither negotiate debugger capabilities nor attach another tab.
- Each diagnostic request has a UUID, bounded replay history and bounded
  connection count. Requests validate against one shared Python schema;
  replies contain static status metadata, never task/page content or tokens.
- Use a fixed Rust-owned `probe_connection()` method to issue
  `Page.getLayoutMetrics` against the already-owned active tab. Validate the
  response shape and discard all browser data. Python cannot choose a method
  or supply executable code through this API.
- Probe semantic observation separately while idle. Skip browser probes during
  active, paused or approval-suspended runs. Do not allow task scheduling while
  a diagnostic probe owns the browser. This protects ElementRegistry state.
- The service owns the probe task even if its client disconnects. Closing the
  service closes the backend transport and awaits probe settlement: cancelling
  an `asyncio.to_thread` waiter alone does not cancel Rust work.
- Preserve reviewed native error categories, operation, recoverability,
  allowlisted CDP method and numeric protocol code across PyO3. Never propagate
  raw page/provider exception text into traces or product messages.
- Keep the 8 MiB frame limit and add a 256-level JSON nesting limit. A small
  lexical preflight counts JSON brackets outside quoted strings before parsing.
  `serde_stacker` supports safe parsing within that bound because real DOM
  responses can exceed `serde_json`'s default 128-level limit. Parse errors are
  reduced to fixed safe categories and propagated to pending commands; payload
  bytes and parser diagnostics are never exposed.
- Doctor never invokes providers. Local Laya health checks remain permitted;
  no OpenAI/Jev inference is needed to establish browser readiness.

## Compatibility

The binding adds one method; existing callers and serialized browser schemas
remain compatible. Native exceptions remain `RuntimeError` with additive safe
attributes. Diagnostic requests are a local administrative branch, not a new
web API or extension command. Existing extension protocol v1 remains supported.
Additive timeline events follow the append-only trace rules.

## Alternatives

A separate diagnostic socket would duplicate endpoint lifecycle and ownership
checks. Connecting as a second normal extension would consume or tear down the
active session. Using cached tab state cannot prove CDP liveness. Running a
model-backed task to test connectivity spends credits before the browser
infrastructure is established.

## Consequences and limits

`browski doctor --extension` can distinguish connection from idle browser
readiness without a paid call. A successful probe is an instantaneous health
observation, not a guarantee that a later action or arbitrary website task
will succeed. Same-user processes with the private token are trusted local
administrators; this does not defend a compromised operating-system account.
Origin consent, capability negotiation, owned tabs, verification, approvals and
checkpoint sanitation remain enforced.
