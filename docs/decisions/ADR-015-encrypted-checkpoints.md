# ADR-015: Encrypt durable SQLite checkpoints

Date: 2026-10-08 · Status: accepted

## Context

LangGraph checkpoint state and pending writes can contain the user task,
browser observations, provider-derived summaries, and action details. SQLite
checkpoint payloads therefore need protection at rest while retaining
LangGraph's normal resume behavior. The checkpointer also stores framework
metadata and thread identifiers in separate columns.

## Decision

- Keep `AsyncSqliteSaver` and its resume semantics, but wrap LangGraph's
  `JsonPlusSerializer` with authenticated AES-256-GCM serialization for both
  checkpoints and pending writes. Use a fresh nonce for each serialized value
  and authenticate the inner serializer type along with its payload.
- Obtain the encryption key from the OS keyring when a usable secure backend
  is available. Otherwise, for a new database, store one generated key for
  this BROWSKI installation and user in a private local file. On supported
  Unix filesystems, require owner-only directory and file permissions, reject
  symlinks and unsafe ownership, and create atomically. This fallback protects
  against ordinary access by other local users; it does not protect against
  compromise of the same user account.
- Never silently regenerate a key for a non-empty checkpoint database. If the
  key is missing, mismatched, or cannot authenticate a value, fail closed.
- Before key lookup or saver setup, inspect existing `checkpoints` and `writes`
  serializer types through a read-only preflight. Reject plaintext or
  unsupported rows without modifying the database. Migration or removal is an
  explicit operator action; no automatic plaintext migration is provided.
- Keep checkpoint metadata and identifiers out of the encryption claim.
  Runtime metadata must remain framework control data. Run IDs are visible in
  plaintext columns; runtime-generated values are UUIDs and caller-provided
  values must pass a bounded non-sensitive slug format. This is validation of
  identifier shape, not secret detection.

## Consequences and limits

Checkpoint payloads and pending writes are encrypted in the database and
SQLite WAL. Metadata columns remain separately visible. The local-file key is
shared across databases for this installation and user; if keyring and file
keys disagree, startup stops rather than choosing one. Losing the key makes
saved checkpoints unreadable. Row deletion through retention does not guarantee
physical erasure from SQLite free pages, WAL history, filesystem snapshots, or
backups. The fallback does not defend against same-user malware or account
compromise. Retention deletion is logical; the application does not promise
physical overwrite or cryptographic erasure of individual runs.

## Validation

Focused tests cover encrypted serializer round trips and fresh nonces,
checkpoint and pending-write ciphertext, tampering and wrong keys, safe key
storage and key mismatch, and byte-preserving rejection of pre-existing
plaintext checkpoint and write rows. These tests do not provide a security
certification or establish protection against compromise of the host account.
