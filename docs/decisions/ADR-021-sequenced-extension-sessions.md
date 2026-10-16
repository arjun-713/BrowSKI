# ADR-021: Sequenced extension messages for long sessions

Status: Active

Date: 2026-10-16

## Context

The extension validator remembered every UUID received on a connection and
closed it after 4,096 messages. CDP responses and browser events consumed this
budget during observation, independently of the number of agent actions.
A crowded-page regression reproduced the exact rejection at 4,096 messages.
Increasing the cap would postpone the failure and increase retained state.

## Decision

Extension 0.1.7 adds a strictly increasing `sequence` to outgoing protocol v1
envelopes. The handshake selects sequenced mode for the authenticated
connection. All following envelopes must use that mode and a larger positive
JavaScript safe integer. The extension worker owns the counter; it may keep
increasing across Native Messaging reconnects.

The runtime keeps the last accepted sequence plus a bounded recent UUID
window. An old packet is rejected by its sequence even after its UUID has
been evicted. Reusing a recent UUID with a fresh sequence is also rejected.
Validation failures do not advance either guard. Authentication, tab ownership,
capability validation, approvals, message-size limits and command correlation
continue to apply independently.

This protects against replay of captured envelopes. It does not authenticate
a newly forged envelope from a compromised trusted extension or local owner
process; those remain trust boundaries in the existing threat model.

## Compatibility

The sequence is an additive v1 field selected by its presence on the first
hello. Legacy senders retain the prior bounded lifetime policy. A connection
cannot switch modes after negotiation. The paired runtime/extension upgrade
must precede reloading 0.1.7, since an older strict runtime rejects the field.
No browser-side contract or Rust transport schema changes.

## Evidence

The pre-fix diagnostic recorded `count=4096` and
`extension message replay window is exhausted` on a real packaged extension.
Unit coverage exercises more than 4,096 sequenced messages, bounded cache
retention, old-packet rejection, malformed sequences, mode changes and invalid
payloads. The crowded-page E2E regression additionally checks real observation,
bounded provider projection, execution, verification and displayed completion.
