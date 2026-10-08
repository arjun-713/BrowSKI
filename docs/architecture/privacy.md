# Provider privacy boundary

The Python `ProviderBoundary` is the policy gate for reasoning requests. It
receives the typed `ReasoningContext`, checks the serialized size, applies the
configured privacy mode, and forwards the permitted context to the configured
reasoning provider. Vision uses a separate `VisionProviderBoundary` because a
screenshot is a different data type with different redaction needs.

## Modes

- `standard` forwards the bounded reasoning context unchanged. Page content may
  therefore reach the configured remote provider.
- `privacy_first` performs heuristic text redaction and request-scoped token
  substitution before forwarding. The current implementation recognizes
  selected common provider-token formats, PII patterns, credential-like field
  names, and labels on semantic fields. Returned tokens are restored only in
  typed action `text` and `value` fields, then the local mapping is cleared.
- `offline` rejects a remote reasoning call before invoking the provider.

The pattern recognizer is intentionally a limited best-effort filter. It is
not a universal secret detector, and tokenization can change meaning or miss
values without recognized formats or labels. In particular, browser page
text is untrusted and can contain instructions or sensitive content. The
Luna prompt labels page text as evidence, but prompt instructions do not
provide a security boundary.

Cross-tab transfers have a separate explicit path. A bounded user task grammar
names one source label and destination label. Luna can return only a current
semantic source ref; the graph reads the value from the current visible,
non-input Rust snapshot and stores a typed, bounded evidence record with source
tab/ref/generation. It rejects recognized sensitive labels and common secret
or PII patterns. A later finite action can use that value only for one unique
matching input while the source tab remains owned. Legacy `acquired_facts` are
not treated as transfer evidence. This is explicit value transfer, not page
instruction trust; arbitrary page text still cannot add candidate actions.
The recognizer is best-effort, so standard mode may send the authorized source
text to the configured provider and privacy-first may redact or tokenize it.
The contract and rationale are recorded in
[ADR-017](../decisions/ADR-017-explicit-cross-tab-text-transfer.md).

The provider adapter emits metadata such as provider, operation, outcome,
timing, and token counts. It does not log request or response content, raw
exception messages, or the configured API key. Exception messages from the
underlying SDK are wrapped because they may include request details.

Durable SQLite checkpoints use an authenticated AES-GCM serializer for both
checkpoint state and pending writes. The serializer authenticates its inner
type and payload, rejects plaintext legacy blobs, and fails closed when a key
is missing, mismatched, or unable to authenticate saved data. The encryption
key is stored in the OS keyring when available. If that backend is unavailable
for a new database, BROWSKI may use a generated key in a private local file
with owner-only directory and file permissions. That fallback protects against
other local users with ordinary access, but it is not an OS-managed secret
store and does not protect against compromise of the same user account.

SQLite checkpoint metadata remains separate from the encrypted state blobs.
Runtime metadata must contain only framework control fields. Run IDs are
visible plaintext identifiers: BROWSKI generates UUIDs by default, and
caller-provided values must be bounded non-sensitive slugs. This syntax check
is not secret detection. Do not place user task text or provider/page content
in checkpoint metadata or run IDs. Local observability stores typed aggregate
counters only: elapsed wall-clock duration, action attempts, failed
verifications, recoveries, browser-code calls, vision calls, Luna call/effort
counts, and Laya shadow decision counts. It does not persist provider values,
action labels, page text, or provider reasoning. Duration spans pause and
restart gaps; it is not active interaction time. Metric rows are removed in
the same retention transaction as their run metadata and checkpoints, subject
to the SQLite/WAL residuals described below.
Before opening a saver, a read-only preflight scans every existing
`checkpoints` and `writes` row. It rejects plaintext or unsupported serializer
types across the database before key setup or writes, and leaves the database
unchanged. Back up and migrate or remove rejected databases explicitly. Backups
and SQLite WAL files contain encrypted state blobs; deleting a key makes those
checkpoints unreadable. Retention cleanup removes rows logically; SQLite free
pages, WAL history, filesystem snapshots, and backups may retain older bytes,
so cleanup is not guaranteed physical erasure.

The local-file fallback key is shared by this BROWSKI installation for the
current user, rather than derived from an individual database. If the keyring
and fallback file contain different keys, startup fails closed. If the
keyring later becomes unavailable and there is no fallback key for a database
that already contains data, startup also fails closed instead of creating a
replacement key.

Screenshot redaction is not implemented. The vision boundary therefore allows
screenshots only in `standard` mode and blocks them in `privacy_first` and
`offline` modes. This behavior must remain fail-closed until an enforceable
sanitized-image path is implemented and tested.

See [privacy modes](../user/privacy.md) for operator guidance and the
[threat model](../security/threat-model.md) for residual risks.
