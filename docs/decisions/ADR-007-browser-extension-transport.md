# ADR-007: Browser extension CDP proxy and host transport

Date: 2026-10-06 · Status: accepted; Native Messaging and shared runtime backend implemented

## Context

BROWSKI needs an attached-browser mode in which the user explicitly attaches
the extension to the current Chrome tab. The extension's `chrome.debugger` API
is the available browser-mediated CDP transport for this mode. Rust remains
the semantic browser engine and Python remains the agent runtime; the extension
must not become an agent or own browser policy.

The production extension needs to relay CDP messages to the local runtime.
Transport candidates are Native Messaging and a loopback HTTP/WebSocket
service. Chrome's debugger API exposes methods and events to extension code,
not a raw CDP WebSocket that can be handed to Rust. A Rust `BrowserBackend`
interface, including `ExtensionCdpBackend`, is therefore the boundary that
normalizes the extension's allowlisted proxy protocol into the existing
runtime contracts.

**Revision note:** This decision supersedes the initial ADR-007 draft that
excluded `chrome.debugger` and treated existing-tab attachment as unsupported.
The selected product direction now requires attached-browser mode. The
extension is accepted only as an allowlisted transport proxy; Rust ownership
of CDP normalization, observation, identity, execution policy, verification,
and recovery remains unchanged.

## Options considered

1. **Authenticated localhost HTTP/WebSocket.** Easy to develop and inspect,
   but opens a local listener. It requires loopback-only binding, strict
   extension-origin checks, per-process credentials, bounded protocol
   validation, and careful extension host-permission/CSP setup.
2. **Chrome Native Messaging.** Chrome starts a registered local host and
   exchanges length-prefixed JSON over stdio. It avoids a listening socket and
   binds callers to extension IDs through `allowed_origins`. It requires
   platform-specific installation, registration, updates, and crash recovery.
3. **Extension-contained reasoning or browser runtime.** Avoids a host
   installation, but moves provider policy, agent state, observation, or action
   policy into TypeScript, violating the accepted Rust/Python ownership
   boundaries and Manifest V3's packaged-code model.
4. **Managed-browser-only UI.** A force-installed extension can serve
   enterprise Chrome deployments, but policy does not provide a general
   runtime transport or ordinary-user attachment path.

## Decision

Use `chrome.debugger` as an **allowlisted transport proxy** for the user-
confirmed active tab in both development and production. The extension may call
`attach`, forward only Rust-originated allowlisted `sendCommand` requests,
return their correlated responses, and forward only allowlisted `onEvent`
events. `BrowserBackend` and `ExtensionCdpBackend` in Rust own CDP method
schemas, normalization, event semantics, DOM/AX/layout observation, element
identity, action policy, verification, and recovery. Python retains planning,
provider policy, memory, and high-level recovery. The extension does not
select actions, issue model-derived commands, generate selectors, or make
success decisions.

Use **Native Messaging in production**. A thin native host validates the
extension origin and versioned message envelope, then relays typed CDP requests,
responses, and events to the Rust runtime. Use **authenticated loopback-only
HTTP/WebSocket for unpacked development** with an exact dev extension origin,
fixed loopback endpoint, and per-process random credential. Do not expose a
wildcard network listener by default.

Attachment requires the user to invoke the extension on the current active
tab, see the tab origin, and explicitly confirm in the side panel. Bind the
session to that captured `tabId` and an attach generation; never retarget it
when active tabs change. Revoke/detach on user request, cross-origin
navigation, tab close, debugger `onDetach`, extension/runtime disconnect, or
stale protocol session. DevTools opening on an attached tab can detach the
extension debugger. Reattachment always requires fresh user consent.

The extension requires Chrome's `debugger` permission and should also use
`activeTab` for the temporary, user-invoked current-tab context. The debugger
API exposes only Chrome's documented protocol domains. Rust's backend owns a
narrower, versioned method/event allowlist within that surface; unsupported or
unknown commands fail closed. The exact allowlist must be pinned to the
supported Chrome protocol version and generated/validated against Rust's typed
backend contract rather than maintained as independent extension policy.

## Consequences

- Attached-browser mode can control one explicitly confirmed active tab. It
  does not silently enumerate or attach to every user tab.
- The Rust `CdpTransport` contract now separates the `BrowserSession` command
  and event surface from its managed WebSocket implementation. The extension
  transport and its target/bootstrap lifecycle remain outstanding.
- Native Messaging production packaging must register and update a host on
  each supported OS and keep the Chrome extension ID stable.
- The native host accepts only the expected extension origin, validates
  version, message size, request IDs, tab/session/attach generation, and
  capabilities, and sends diagnostics only to stderr.
- The extension service worker is a transport endpoint, not durable task
  state. Python/Rust checkpoints and browser state must remain authoritative
  when the panel closes or the host disconnects.
- `chrome.debugger` carries a powerful permission warning and Chrome DevTools
  opening for the attached tab terminates the extension debugger session.
  Enterprise policy can block debugger attachment; detach/conflict errors are
  surfaced to the runtime and user.
- Chrome documents only a subset of CDP domains for `chrome.debugger`.
  `Browser` and other unavailable domains, unlisted methods, browser-wide
  endpoint semantics, arbitrary debugging targets, remote runtimes, and other
  browsers remain outside this decision.
- The development loopback path is not a production alternative: it is
  reachable by local processes and must enforce origin and credential checks
  server-side, not rely on CORS alone.

## References

See [the extension architecture note](../architecture/browser-extension.md)
for the transport envelope, attach flow, method/event surface, permission
plan, lifecycle, risks, and official Chrome documentation links (accessed
2026-10-06).
