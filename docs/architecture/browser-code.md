# Controlled browser-code boundary

BROWSKI's normal interaction path uses semantic browser observations and typed
`BrowserAction` values executed and verified by the Rust browser core. Browser
code is an exceptional capability for deterministic page operations that
cannot be expressed by that action contract. It is not an alternate planner
or a default interaction path.

## Current implementation

The Python `BrowserCodePolicy` validates a request's purpose, reason, script
size, timeout, result-size limit, and declared Pydantic result schema. It
produces safe trace metadata containing a script digest rather than script or
result contents. The capability defaults to disabled. Even when a caller
enables the policy, execution fails closed because the current Rust binding
does not expose a suitably isolated evaluator.

This is a policy scaffold, not an available product feature. The runtime must
not route a `BrowserCodeRequest` through the existing page-realm CDP
`Runtime.evaluate` or `Runtime.callFunctionOn` helpers. Those helpers are
internal browser mechanics, and some accept dynamically constructed source.
Forwarding either CDP method as an unrestricted extension capability would
turn the bridge into a general page-code execution channel.

## Requirements before enabling execution

An implementation must provide all of the following at the execution
boundary, not merely as prompt instructions:

- explicit configuration and capability approval, disabled by default;
- a narrowly defined operation or language subset with no shell, filesystem,
  arbitrary local-process, or unapproved network access;
- a hard execution deadline and bounded, JSON-only result;
- typed result-schema validation before returning data to the agent;
- verification against a fresh semantic observation where the operation
  changes page state;
- a structured trace event with purpose, reason, digest, limits, duration,
  and outcome, while excluding source and result values;
- privacy-boundary inspection before any result or page-derived content is
  sent to a model;
- regression tests for page prompt injection, exfiltration attempts, timeout,
  oversized results, malformed results, and cancellation.

If the proposed browser context cannot enforce these restrictions, the request
must remain unavailable and the agent must return to semantic actions or
escalate to the user. A JavaScript source-size limit alone is not a sandbox.

## Relationship to attached-browser mode

The extension bridge forwards only explicitly validated CDP commands. It
currently rejects `Runtime.evaluate` and `Runtime.callFunctionOn`. Do not add
either method to its generic command allowlist to make browser-code work. An
attached-browser implementation must use a separately reviewed capability
contract with equivalent enforcement and must continue to share the Rust
semantic browser engine.

See [ADR-011](../decisions/ADR-011-browser-code-remains-disabled.md) for the
decision to keep execution disabled until those controls exist.
