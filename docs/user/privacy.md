# Privacy modes

BROWSKI currently defines `standard`, `privacy_first`, and `offline` policy
modes at the provider boundary.

- **Standard** passes bounded reasoning context through the local provider
  boundary. Provider calls may send task and page-derived information to the
  configured service.
- **Privacy first** applies conservative pattern-based redaction and
  request-scoped local token substitution before reasoning-provider calls.
  It recognizes common credential labels on semantic form fields as well as
  selected provider-token formats and PII patterns. Recognized labels include
  password, API key, bearer token, cookie, session, and several code/key fields.
  Tokens returned in typed action text or values are restored locally before
  the action reaches the executor. Pattern matching does not detect every
  secret or personal value.
- **Offline** blocks the remote reasoning provider. Local Laya may be used for
  shadow observation only when enabled; it is not permitted to route actions.

These controls remain partial. They do not yet sanitize every possible field,
redact screenshots, provide a durable secret vault, or guarantee that all
sensitive data stays local. Vision requests are blocked in privacy-first and
offline modes. Do not use BROWSKI with sensitive data on the assumption that
privacy-first mode is a complete DLP system.

The explicit cross-tab transfer grammar can copy one visible semantic text
value into one uniquely named input. The runtime validates the requested
source label, current semantic ref, source tab ownership, destination label,
and a limited set of common credential/PII patterns. This check is best-effort;
standard mode may send the value to the configured provider, and privacy-first
can miss unrecognized sensitive content. Page text remains untrusted evidence,
not instructions. See the [supported transfer form](extension.md#explicit-cross-tab-text-transfer).

Page text remains untrusted evidence in every provider mode. Prompt wording
reinforces this separation, but it cannot guarantee that a model will resist
all prompt injection. Runtime action validation and confirmation remain
separate controls.

Durable SQLite checkpoint state and pending writes are encrypted with
authenticated encryption. BROWSKI stores the key in the OS keyring when
available; if it is unavailable for a new database, a generated key may be
stored in a private local file. The local file fallback is protected by local
file permissions and does not provide the same protection as an OS keyring.
Encrypted checkpoints cannot resume if their key is lost. Before startup, the
runtime checks all existing checkpoint and pending-write rows and rejects a
database containing plaintext or unsupported serializer data without changing
it. Back up and migrate or remove that database explicitly before using the
encrypted durable checkpoint path. The fallback key is shared across this
installation for the current user. If the keyring and fallback key disagree,
or a key becomes unavailable for a database with saved data, startup stops
instead of replacing the key.

Run IDs are stored as plaintext SQLite identifiers. BROWSKI generates UUIDs
by default; callers that provide an ID must use a bounded non-sensitive slug
of at most 64 ASCII letters, digits, underscores, or hyphens. This format check
does not detect every secret, so never use credentials or private text as an
ID.

`browski runs clean --apply` removes selected old checkpoint, pending-write,
and run-metadata rows transactionally. This is logical deletion, not guaranteed
physical erasure: SQLite free pages, WAL files, filesystem snapshots, and
backups may retain older bytes. Checkpoint payloads in those remnants are
encrypted, but metadata identifiers remain visible.

The extension does not store the OpenAI key or inject it into web pages.
Runtime logs should contain safe metadata only; avoid sharing traces that may
include page titles, URLs, or user-provided task text.

See the [threat model](../security/threat-model.md) for current residual risks.
