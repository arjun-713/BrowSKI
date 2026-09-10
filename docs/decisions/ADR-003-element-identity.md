# ADR-003: Element identity and semantic references

Date: 2026-09-10 · Status: accepted

## Context

The agent needs element handles that survive the small DOM churn of modern
web apps (re-renders, class changes, reorders, insertions) without ever
pointing at the wrong control. CSS selectors break on churn; raw backend ids
die on navigation; screenshots can't name anything.

## Decision

- **Identity is numeric and internal** (`ElementRef { id, alias, generation }`);
  aliases (`@email`, `@billing_continue`) are deterministic model-facing
  conveniences assigned in document order from role/names/labels/context.
- **Fingerprints are multi-signal** (role, accessible name, label, input
  name, placeholder, type, nearby text, ancestry signature, frame path,
  stable attrs, form context). Geometry and backend ids score but never hash.
- **Reacquisition is leveled** (backend-alive → DOM identity → exact
  fingerprint → role+name+context → structural → nearby → refuse).
  Ambiguity refuses; the registry never silently binds.
- **Alias rules**: unique bases stay bare even with form context; colliding
  bases prefer context prefixes, then numbers; residual collisions suffix in
  document order. Root-level (`html/body`) classes are excluded from ancestry
  signatures (frameworks churn them constantly).
- **Contract change note (M2)**: `ElementRef` changed from a bare string to
  `{id, ref(alias), generation}`; `SemanticElement.reference` serializes as
  `ref`. Additive snapshot fields otherwise. Python mirror updated in lockstep
  (see `docs/protocols/versioning.md`).

## Alternatives considered

- CSS-selector identity: rejected (breaks on exactly the churn we must survive).
- Backend-id-only identity: rejected (dies on navigation/re-creation; kept as
  level-1 signal only).
- LLM-generated aliases: rejected (nondeterministic; identity must not depend
  on model output).
- Always-prefixing context (`@application_email`): rejected as noisy; context
  applies on collision only.

## Consequences

- M3 executor resolves targets through `resolve()` + generation checks; stale
  refs are detectable, ambiguous ones unresolvable by construction.
- Alias stability across observations is gated by the M2 stress suite.
