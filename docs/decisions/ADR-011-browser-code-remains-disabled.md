# ADR-011: Keep browser-code execution disabled until enforceable isolation exists

Date: 2026-10-07 · Status: accepted

Amended by [ADR-012](ADR-012-fixed-browser-mechanics-in-extension-transport.md)
for fixed Rust-owned observer mechanics. The browser-code decision is narrowed
by [ADR-014](ADR-014-isolated-semantic-data-transforms.md) for pure transforms
over a bounded Rust-owned semantic projection only. Model-authored live-page
code remains disabled under this decision.

## Context

The M9 request and result policy scaffold has size and time budgets, a
capability switch, schema validation, and safe trace metadata. It does not
provide an execution sandbox. The current Rust browser core has internal CDP
helpers for `Runtime.evaluate` and `Runtime.callFunctionOn`; they execute in
the page context, and some call sites construct JavaScript dynamically from
action values. Those helpers were designed for browser mechanics, not as a
general-purpose code tool.

The extension also forwards a validated subset of CDP. Exposing page-code
methods there would broaden the authenticated bridge into a script execution
interface. Prompt instructions, a small source limit, and result validation do
not prevent page code from reading sensitive page data or attempting network
exfiltration.

## Decision

- Keep browser-code execution disabled by default and fail closed even when
  the configuration capability is set to enabled.
- Do not route `BrowserCodeRequest` through existing page-realm CDP helpers.
- Do not add `Runtime.evaluate` or `Runtime.callFunctionOn` to the extension's
  generic debugger command allowlist.
- Revisit execution only when the runtime can enforce the required operation
  subset, time/result limits, trace policy, privacy boundary, and regression
  tests at the execution boundary.

## Consequences

M9 has a policy scaffold but is not an available product capability. Tasks
that need arbitrary page code must use semantic actions when possible or stop
for escalation. This avoids presenting a capability gate as a sandbox.

The decision does not prohibit narrowly scoped Rust-authored browser
mechanics. Those remain internal implementation details and must not become
model-controlled code execution through the extension transport.

## Validation

Policy tests verify disabled-by-default behavior, validation budgets, schema
checks, bounded results, trace redaction, and fail-closed execution. Static
inspection of Rust call paths found dynamic code construction in the native
select helper; this supports keeping the generic extension execution methods
unavailable. No page-code executor is claimed or enabled.
