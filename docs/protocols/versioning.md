# Versioning and compatibility

We want future extensions/SDKs to depend on stable interfaces. Three
versioned surfaces:

## 1. Rust/Python binding API (`browser_agent._core`)

- Version: crate `browser-agent-python` `CARGO_PKG_VERSION`, exposed as
  `_core.__version__` / `core_version()`.
- Patch (0.1.x): additive, backwards-compatible additions.
- Minor/major or any breaking change: ADR + migration notes + coordinated
  update of Rust types, Pydantic mirror, bindings, and tests (never one side
  alone). See `AGENTS.md` §11.

## 2. Serialized contracts

- `SemanticSnapshot.schema_version` (currently 1) and
  `TraceEvent.schema_version` / `TRACE_SCHEMA_VERSION` (currently 1).
- Consumers must ignore unknown fields and reject unknown major versions
  with a clear error (lenient readers, explicit versions).
- Any field removal, rename, or semantic change bumps the schema version and
  requires migration notes here; non-trivial migrations require an ADR.
- Additive Python-only working-memory fields in encrypted LangGraph
  checkpoints do not change the Rust/Python browser binding or
  `SemanticSnapshot` version. Optional reasoning output fields remain
  backward-compatible when omitted. [ADR-017](../decisions/ADR-017-explicit-cross-tab-text-transfer.md)
  documents the provenance and finite-action rules for explicit page-text
  transfers.

## 3. Trace schema

- Trace events are append-only JSON; old readers skip unknown `kind`
  values. New `kind` strings need no version bump, but new *required*
  fields do.

## Extension-runtime bridge

Native Messaging protocol v1 uses the envelope fields `protocolVersion`,
`type`, `eventId`, and `payload` in both directions. Every message has a fresh
UUID `eventId`; the runtime rejects duplicate IDs within a bounded connection
window. Extension 0.1.7 adds an outbound `sequence` field: a positive,
strictly increasing JavaScript safe integer. Its presence in `extension.hello`
selects sequenced mode for that connection; subsequent messages must keep the
same mode. The runtime rejects old sequence numbers even after their UUIDs
leave the bounded cache, permitting long sessions without an unbounded replay
set. Invalid messages never advance the sequence. The counter can continue
across reconnects; each authenticated connection establishes its own baseline.

Legacy senders without `sequence` remain supported with their original
4,096-message lifetime limit. Upgrade the runtime and reload extension 0.1.7
together to use long sessions. Older runtimes reject the additive field;
this is a coordinated v0.x upgrade. [ADR-021](../decisions/ADR-021-sequenced-extension-sessions.md)
records the compatibility and replay policy.

CDP command correlation uses `payload.commandId`, while the internal
Rust/backend protocol uses a separate integer `requestId`.

The shared [hello fixture](../../tests/fixtures/extension/hello.v1.json) is
checked by the TypeScript sender and Python validator tests. The real Chromium
E2E test covers framed Native Messaging, authentication, capability negotiation,
and attached-tab observation without mocking extension APIs.

## Backward compatibility expectations

- v0.x: best effort; breaking changes allowed only with an ADR, migration
  notes, and a minor version bump.
- v1.x (future): binding API and schema v1 frozen; breaking changes ride
  major versions with a deprecation window.
