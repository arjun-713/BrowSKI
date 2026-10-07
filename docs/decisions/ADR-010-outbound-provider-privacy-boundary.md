# ADR-010: Central outbound provider privacy boundary

Date: 2026-10-06 · Status: accepted

## Context

Reasoning and multimodal requests may contain task text, browser content, or
screenshots. Privacy mode must be enforced immediately before data reaches an
external provider, without putting provider-specific policy throughout the
agent graph. Screenshot redaction and complete PII detection are not yet
available.

## Decision

- Route CLI-created remote reasoning and vision providers through the shared
  privacy-boundary module.
- In `standard` mode, forward only the bounded typed provider contract and
  record safe metadata; never log the outbound text or image payload.
- In `privacy_first` mode, apply the current heuristic tokenization to text
  reasoning context using a request-scoped in-memory vault. After the provider
  returns, restore tokens only in typed action `text` and `value` fields.
  Block remote vision entirely until screenshot sanitization is implemented.
- In `offline` mode, block all remote reasoning and vision calls.
- Keep visual findings separate from durable memory and mark them as untrusted
  evidence in the reasoning contract.
- Do not treat these early controls as complete data-loss prevention. Preserve
  their scope limits in user documentation and the threat model.

## Consequences

The CLI enforces privacy policy at provider construction and use. Directly
constructing an adapter outside that boundary is not a supported application
path. Privacy-first currently favors confidentiality over visual capability;
tasks requiring remote image interpretation must stop for user guidance.
Heuristic text redaction may miss sensitive information and must not be
described as a complete guarantee.

## Validation

Fake-provider tests verify privacy-first text redaction and local action-value
restoration, offline blocking, context-size limits, screenshot blocking in
privacy-first/offline modes, and no secret values in CLI configuration output.
Tests do not establish complete PII coverage or provider-side retention
behavior.
