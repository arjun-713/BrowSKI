# ADR-017: Explicit cross-tab text transfer

- Status: Accepted; batch restriction superseded by
  [ADR-018](ADR-018-locally-verified-luna-actions.md)
- Date: 2026-10-08
- Related: [ADR-006](ADR-006-bounded-memory-recovery-safety.md),
  [ADR-008](ADR-008-luna-active-decision-policy.md),
  [ADR-010](ADR-010-outbound-provider-privacy-boundary.md),
  [ADR-015](ADR-015-encrypted-checkpoints.md),
  [ADR-016](ADR-016-extension-owned-tabs.md)

## Context

The finite-action policy allowed values from explicit quoted user task
instructions. It did not provide a trusted way to carry one visible value from
a supporting page into a named input in another owned tab. The older
`WorkingMemory.acquired_facts` map has no source provenance and must not be
interpreted as user-authorized input. Separately, initial planning and replanning
could return a direct action without using the runtime-built finite candidates.

## Decision

Support one bounded grammar:

```text
transfer "Source label" from supporting page into "Destination label"
```

The model can return an `evidence_ref` only alongside one `NEXT_ACTION` during
`CHOOSE_ACTION`. It supplies a semantic ref, never a value. After Luna has
matched its single action exactly to the finite runtime candidate set, the
graph resolves the ref against the current Rust snapshot. It records evidence
only when the active tab is session-owned and the source is a unique, visible,
enabled, non-interactable, non-input semantic element with the exact requested
accessible name and bounded text. Common credential labels and supported
secret/PII patterns are rejected. The typed record includes source tab, ref,
generation, source label, destination label, and the locally read value. It is
kept separate from unprovenanced legacy `acquired_facts`.

A later typing candidate is added only when the task still contains exactly one
matching transfer request, the source tab remains in the owned-tab snapshot and
is not the active destination tab, the stored source and destination labels
are safe under the recognized-label checks, the value passes the supported
pattern checks, and exactly one interactable text input matches the destination
label. Existing explicit input policy values take precedence. The model action
must still exactly match that finite candidate. The evidence value is task data
for this explicitly requested transfer; it is subject to the configured
provider privacy mode. No provider response cache or extra secret cache is
introduced.

Every Luna `NEXT_ACTION`, including a response during initial planning or
replanning, must match the same runtime-built finite candidate set. Model-returned
`candidate_actions` remain unsupported for execution. Transfer evidence is
ignored outside `CHOOSE_ACTION`.

## Consequences

- Old checkpoints remain readable because the working-memory field is
  additive. Current durable checkpoint encryption applies to the new record.
- Existing `acquired_facts` behavior remains compatible, but those facts do
  not authorize input values.
- The grammar is intentionally narrow and may abstain when source or
  destination semantics are ambiguous.
- Pattern and label checks are best-effort. Page content remains untrusted
  evidence; prompt wording is not a security boundary. Standard mode may send
  this user-authorized text to the configured provider, and privacy-first may
  miss unrecognized sensitive content.
- The source value records what was visible at one semantic generation. The
  runtime does not prove that the page's statement is truthful or current in
  the real world.

## Compatibility

This adds optional fields to Python-only reasoning and encrypted checkpoint
working-memory contracts. It does not change the Rust/Python browser binding,
`SemanticSnapshot`, or Native Messaging wire schema. Existing `ReasoningDecision`
responses that omit `evidence_ref` remain valid. The additive durable-memory
field and optional reasoner output are covered by Python tests; see
[protocol versioning](../protocols/versioning.md).
