# ADR-012: Permit fixed Rust-owned browser mechanics in attached mode

Date: 2026-10-08 · Status: accepted

## Context

The semantic Rust observer reads the current URL, document title, scroll
position, and readiness through `Runtime.evaluate`. Its fallback hit test uses
`Runtime.callFunctionOn` on a resolved browser node. Rejecting both methods
unconditionally prevents the existing semantic engine from observing an
attached tab. A real MV3/Native Messaging test exposed this failure.

## Decision

Keep one Rust semantic engine. Permit only the exact read expressions and
fixed observer/executor scripts in `crates/browser-core/src/mechanics/`.
The extension imports those Rust-owned assets at build time; Rust embeds the
same source. The proxy performs admission checks, not observation or element
reasoning.

Require results by value, reject unknown parameter fields, and restrict
hit-test arguments to two finite numeric values. Read, tag, hover, scroll, and
policy-authorized click templates take no arguments. Native input setters take
one bounded string. Select metadata reads take a bounded value and the closed
`value | label` enum. Values travel as CDP arguments, never interpolated into
JavaScript source. Keep tab/session pinning,
authentication, capability negotiation, and replay checks in force. Arbitrary
expressions, changed function bodies, remote-object arguments, and added
execution flags remain denied.

Any further mechanics need the same fixed-template review before attached
mode may use them. Model-authored `BrowserCodeRequest` scripts do not
use this admission path; ADR-011 continues to govern that separate capability.

## Consequences

The extension can relay browser truth reads without becoming another agent or
exposing a general page-code API. Backend connection failures are observable
through safe phase/error-class metadata rather than unhandled task exceptions.
These scripts run in an untrusted page realm; page-defined getters or handlers
remain a residual risk even for trusted browser mechanics.

## Validation

TypeScript tests accept the exact shared assets and reject appended code,
changed function bodies, invalid arguments, and remote-object results. The
real browser test exercises Rust observation, typing, and deterministic
value verification through Chrome's debugger API. A multithreaded Rust
regression checks monotonic wire IDs for 512 concurrent requests. Capacity
reservation precedes synchronous issuance/enqueue locking; no lock crosses
an await. Unsupported capabilities receive per-request errors, while invalid
session identity or replay still closes the transport.
Passing this transport test does not establish model reliability or arbitrary
browser-code isolation.
