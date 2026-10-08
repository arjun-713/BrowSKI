# Browser extension boundary and host transport

**Status:** Accepted product direction per ADR-007. Python Native Messaging
framing, caller-origin validation, Linux host-to-Unix-socket relay, attached
Rust CDP transport, and task dispatch into the Python runtime are implemented.
The extension has task controls, trace messages, and confirmation responses.
Packaged Chromium tests cover the attached task lifecycle and a complete local
multi-tab demo using deterministic provider responses. Live Luna task
acceptance remains unverified.

## Purpose and ownership

The optional Manifest V3 extension is browser-facing product tooling. It
provides the side-panel UI, lets a user explicitly attach BROWSKI to the
current active tab, relays an allowlisted CDP command/event stream, conveys
approval decisions, and shows runtime status. It does not plan tasks, call
decision or reasoning providers, generate selectors, interpret page state,
choose browser actions, verify postconditions, or implement recovery.

Rust remains authoritative for CDP normalization, tab/frame state, DOM,
accessibility and layout observation, element identity, execution policy,
action validation, verification, and low-level recovery. Python remains
authoritative for task planning, orchestration, memory, provider policy, and
high-level recovery. `CdpTransport` now defines the shared command/event
contract used by `BrowserSession`; the existing managed-browser path implements
it with `PersistentTransport`. The attached-browser `ExtensionCdpBackend`
adapts the extension proxy protocol to this same contract without changing the
semantic engine. The extension does not mirror `SemanticSnapshot`,
`ElementRef`, `BrowserAction`, or agent state as a second source of truth.

In attached-browser mode, Chrome's `chrome.debugger` API is a transport proxy
only. Extension code calls `chrome.debugger.attach()`, `sendCommand()`, and
forwards `onEvent` messages on behalf of `ExtensionCdpBackend`; it does not
normalize observations or authorize actions. This preserves Rust ownership
without requiring a raw CDP WebSocket that Chrome does not expose through the
extension API. Initial attachment is limited to the explicitly selected active
tab. Supporting tabs use the bounded ownership map in
[ADR-016](../decisions/ADR-016-extension-owned-tabs.md); Chrome numeric tab IDs
remain in the extension and Rust receives opaque tab/session identities.

## Transport decision

The browser attachment mechanism is `chrome.debugger` in both development
and production. The production/development distinction is how the extension
relays the typed proxy protocol to the Rust runtime.

### A. Authenticated localhost HTTP/WebSocket — development

A development extension could connect to the local runtime over an authenticated
HTTP/WebSocket endpoint. This is simple to inspect and iterate on, but creates
a listener reachable by other local processes and potentially targeted by web
pages through DNS rebinding, CSRF, or WebSocket-origin mistakes.

Bind only to loopback, check the exact development extension origin, require a
high-entropy per-process credential, bound messages, and support reconnects.
The extension needs narrowly scoped optional host permissions and an exact
extension-page CSP `connect-src` entry.

**Decision:** permitted for a separately justified development implementation,
but not implemented in the current product. Both development and installed
builds use Native Messaging. Any future loopback variant must use an exact
extension origin, ephemeral authentication and loopback-only binding.

### B. Native Messaging — production

Chrome starts the registered native host and provides a bidirectional framed
JSON pipe. The host validates Chrome's caller origin against the configured
extension ID, checks that the local runtime socket and its parent directory
are owned by the current user and inaccessible to other users, then relays
bounded JSON frames. The runtime validates the versioned message schema and
negotiated debugger capabilities. The service authenticates the host and
connects the attached Rust backend to Python task orchestration. No network
listener is required.

Native Messaging requires per-OS host installation, registration, signing or
trusted package distribution, and updates. Exact `allowed_origins` binds the
host to the production extension ID. The host also validates Chrome's caller
origin argument and native frame shape. The runtime remains responsible for
validating protocol messages and capabilities. Host crashes close the port
and require bounded reconnection.

**Decision:** production recommendation. The native host is transport glue,
not a browser backend, agent, or policy authority. Rust remains the only owner
of the CDP domain contract and semantic browser state.

### C. Extension-contained reasoning or runtime

Keeping reasoning or browser semantics inside the extension avoids host
installation, but relocates provider calls, secrets, workflow state, or
observation/action policy into TypeScript. This conflicts with the Rust/Python
ownership boundary. Manifest V3 also disallows remotely hosted executable
code and makes long-running task execution depend on browser UI lifecycle.

**Decision:** rejected. Extension code forwards typed transport messages and
renders runtime-supplied UI state only.

### D. Managed-browser-only UI

A managed Chrome deployment can force-install and configure the side panel and
limit extension settings by enterprise policy. It requires enterprise
ownership, does not itself provide the local runtime transport, and is not the
general consumer installation path. Managed host restrictions can block
`chrome.debugger.attach()` for all targets.

**Decision:** not the general product path. Enterprise policy may distribute
the same Native Messaging architecture but does not change ownership rules.

### Selected production topology

```text
Python agent ↔ Rust BrowserBackend / ExtensionCdpBackend
                           │ versioned typed proxy protocol
                           ▼
             Native Messaging host (thin relay)
                           │ Native Messaging Port
                           ▼
Chrome service worker ↔ chrome.debugger proxy ↔ user-confirmed active tab
                           │
                    Chrome side panel
```

The user invokes the extension for the current tab, sees the tab origin and
permission warning, then explicitly confirms attachment in the side panel.
The extension pins that exact `tabId`; it must not silently retarget when the
active tab changes. The service worker resolves the current tab from the user
action, displays its origin, then waits for the side-panel attach confirmation.
It creates a fresh attach-generation nonce only after confirmation. Messages
from the host/runtime cannot create or broaden consent. The host accepts traffic
only from the production extension ID. Rust tracks the session and interprets
CDP; if attachment or transport fails, the runtime receives a typed failure
and does not report a successful browser action.

### Development topology

```text
Rust ExtensionCdpBackend ↔ authenticated loopback HTTP/WebSocket
                                      │
Chrome service worker ↔ chrome.debugger proxy ↔ confirmed active tab
```

Bind only `127.0.0.1` (and separately `::1` if intentionally supported), use
a fixed documented port, reject non-loopback peers, and check `Origin` against
the exact development extension origin. Mint a high-entropy, short-lived
random credential for each runtime process and require it during connection
setup. Do not put the credential in page content, URLs, logs, or persistent
extension sync storage. Validate message schema, version, size, request ID,
tab/session ID, and capability on every message. Never expose the endpoint on
`0.0.0.0`, a LAN address, or a public tunnel by default.

Loopback plus a token is defense in depth, not a sandbox against hostile local
software. A webpage can attempt to contact local services, so the server must
not rely on CORS alone; enforce origin and credential checks server-side. The
WebSocket connection is a live channel, not durable task state: reconnect and
resume using runtime session IDs and event cursors.

## Protocol and capability rules

Use one versioned JSON envelope for both transports. Each request and response
has a protocol version, message type, request/correlation ID, attach generation,
and explicitly typed payload. An attach request names the user-confirmed
tab ID; after `chrome.debugger.attach()` succeeds, the extension returns an
attached event with that same tab ID and a runtime session ID. CDP requests,
responses, and events must match the active attach generation. Events carry a
monotonically increasing sequence or cursor so reconnect can detect gaps and
request a fresh runtime snapshot. Reject unsupported major versions, unknown
message types, oversized messages, invalid IDs, stale sessions, and
capabilities the UI has not been granted.
Do not serialize provider credentials, cookies, page form values, or full page
snapshots into extension storage or logs.

Expose only UI/session capabilities, for example:

- request attachment to the explicitly selected active tab;
- relay Rust-originated CDP requests from `ExtensionCdpBackend` and return
  their correlated responses;
- forward only allowlisted CDP events from the attached tab to Rust;
- submit a user task or an explicit approve/deny response;
- receive runtime lifecycle, progress, and user-approval-required events;
- request a fresh runtime status after reconnect.

The extension's CDP proxy has no action-selection authority. It rejects
requests outside the runtime's negotiated, versioned allowlist and validates
tab ID, session ID, method/event name, request ID, and payload size. Rust
validates again before acting on every command. Raw arbitrary JavaScript,
selectors, unrestricted network interception, cookie access, unbounded
screenshots, provider selection that bypasses Python policy, and filesystem or
shell operations are not capabilities. High-risk approval remains tied to the
pending runtime action and checkpoint, not a UI-only boolean.

### CDP command and event surface

Chrome documents `chrome.debugger` as an alternate CDP transport with a
restricted domain list. The browser layer must use only methods and events
within the domains documented by Chrome, and the runtime must further narrow
that list to commands required by its typed `BrowserBackend` contract. The
extension must not maintain an independent policy list: the Rust backend
negotiates a protocol/allowlist version during attach and the proxy enforces
that version as a transport ceiling.

The initial method/event review should cover the Rust semantic runtime's
existing needs: `Accessibility`, `DOM`, `DOMSnapshot`, `Input`, `Page`,
`Runtime`, and `Target` domains. Representative command candidates include
`Accessibility.getFullAXTree`, `DOM.getDocument`,
`DOMSnapshot.captureSnapshot`, `Input.dispatchMouseEvent`,
`Input.dispatchKeyEvent`, `Input.insertText`, `Page.getFrameTree`,
`Page.navigate`, `Page.reload`, `Runtime.enable`, and `Target.setAutoAttach`.
Representative events include `Page.frameNavigated`,
`Page.frameStartedLoading`, `Page.frameStoppedLoading`,
`Runtime.executionContextCreated`, `Runtime.executionContextDestroyed`,
`Runtime.executionContextsCleared`, `Target.attachedToTarget`, and
`Target.detachedFromTarget`. These names are candidates only: exact command and
event names, parameters, and supported Chrome versions must be pinned by the
Rust backend protocol contract. Preserve the `sessionId` Chrome includes for
flat child-target events and bind it to the correct tab/attach generation.
Chrome's flat `Target` sessions are available from Chrome 125; out-of-process
iframe auto-attach is not recursively transitive, so deeper frames require
explicit follow-up attachment. Treat frame coverage as incomplete until Rust
integration validates it. The extension must not accept dynamic method names
from model output or extension UI input.

`Runtime.evaluate` is especially sensitive: if the typed Rust implementation
needs it, accept only Rust-generated, bounded protocol requests; never accept
page text, model output, or extension UI input as an executable expression.
Commands that Chrome does not expose through `chrome.debugger`, browser-wide
commands, and methods not in the Rust backend's negotiated list fail closed.

### Native Messaging wire and authentication

Chrome's native messaging transport uses UTF-8 JSON preceded by a 32-bit
message length in native byte order. Chrome documents a maximum of 1 MiB for a
single host-to-extension message and 64 MiB for an extension-to-host message.
Set substantially smaller application limits and chunk only explicitly
streamable data. Keep stdout exclusively for framed protocol messages; send
diagnostics to stderr.

The host manifest should allow only the stable production extension ID. Chrome
passes the caller extension origin as the native host's first argument; the
host should compare it to the exact expected origin as a second check. Treat
this as caller-extension binding, not user authentication: rely on OS package
installation and file permissions for the native executable/manifest, and
never accept arbitrary extension origins. Content scripts cannot call native
messaging directly; if page-derived data is ever forwarded by the extension,
validate its sender origin and sanitize it first.

## Permissions and browser surface

Declare only the permissions required for the selected flow:

- `manifest_version: 3`, packaged local code, and an event-driven service
  worker;
- `sidePanel` for the BROWSKI UI;
- `nativeMessaging` for the production host;
- `debugger` because the extension proxies CDP for the attached tab;
- `activeTab` so the user's extension action grants temporary access to the
  current tab; it is revoked on cross-origin navigation or tab close;
- `storage` only for non-sensitive UI preferences or reconnect metadata.

The `debugger` permission causes a strong install warning because it grants
powerful page-debugging access. `chrome.debugger` itself does not require host
permissions, and the API is not scoped by `activeTab`; that permission only
limits temporary host access such as reading current-tab details. Therefore,
the service worker must enforce the owned-tab attachment state machine and fresh
user consent in code, while Rust independently enforces the negotiated
session/capability allowlist. Avoid broad `host_permissions`, `tabs`, and
content-script matches unless a concrete UI need requires them. Capture one
`tabId` from the user action, show its origin, and require separate explicit
attach confirmation. Do not enumerate or attach tabs in the background. Reject
restricted browser pages and any target Chrome does not expose.

For a future localhost development transport, declare only the selected loopback origin(s) in
optional host permissions and request them only in the development build. Add
the exact development WebSocket endpoint to extension-page `connect-src` CSP;
do not weaken script policy or ship the development endpoint in production.
Confirm the supported Chrome minimum before relying on these APIs: Side Panel
is available from Chrome 114, native messaging service-worker lifetime support
from Chrome 105, and WebSocket activity resets from Chrome 116.

## Lifecycle and failure handling

Manifest V3 service workers are event-driven and can stop after inactivity;
global variables are not durable. Persist only small, non-secret reconnect
metadata, and reacquire runtime/session state after every worker start. A
Native Messaging port keeps the worker alive while connected in supported
Chrome versions, but this is not a reason to make task state depend on worker
memory. Reconnect on port disconnect, host crash, extension update, or browser
restart, using bounded backoff and explicit disconnected/error UI.

An active debugger session keeps the MV3 worker alive starting in Chrome 118;
a Native Messaging connection does so starting in Chrome 105. An active
WebSocket can extend the worker lifetime when messages are exchanged within
Chrome's activity window, starting in Chrome 116. These are live-connection
behaviors, not durable execution guarantees. Register event listeners at
service-worker top level, persist no authority in globals, and restore transport
state after startup. Do not assume a dormant extension can be woken by a
server-initiated WebSocket. Runtime tasks and checkpoints belong in Python/Rust
and must survive the extension closing.

The side panel is a UI page, not a background daemon. It may be closed,
recreated, switched between tabs, or reloaded during extension updates. It
must rebuild its view from the runtime status/event cursor after each load.
The offscreen API is not a workaround for this lifecycle or a hidden agent
host: offscreen documents have restricted extension API access and should be
used only for a documented DOM-only need.

Classify disconnects explicitly (extension port closed, native host absent,
protocol mismatch, permission denied, runtime unavailable, stale session,
policy-blocked debugger attach, target closed, or debugger detached by DevTools).
On `chrome.debugger.onDetach`, user revocation, cross-origin navigation, tab
closure, host/runtime disconnect, or extension update, stop forwarding, notify
Rust, invalidate page-local element references, and pause or fail the task with
evidence. Require fresh user consent before reattaching; never auto-attach a
new active tab. Chrome documents that invoking DevTools for an attached tab
terminates the extension debugger session. Do not report success from a UI or
transport call; show the Rust/Python runtime's verified terminal result.

## Unsupported domains and risks

- This proposal supports Chrome/Chromium Manifest V3 only. Other browser
  extensions APIs and their permission/lifecycle behavior are unverified.
- Attached mode begins with the active tab the user explicitly confirmed,
  and can create at most seven supporting HTTP(S) tabs through typed synthetic
  lifecycle commands. It does not adopt arbitrary existing tabs or popups,
  restore page-local state after browser restart, or control other extensions'
  or browser-internal pages. Stop detaches debuggers and leaves tabs open.
- `chrome.debugger` does not expose the full CDP surface. Chrome's current
  documented domains are Accessibility, Audits, CacheStorage, Console, CSS,
  Database, Debugger, DOM, DOMDebugger, DOMSnapshot, Emulation, Fetch, IO,
  Input, Inspector, Log, Network, Overlay, Page, Performance, Profiler,
  Runtime, Storage, Target, Tracing, WebAudio, and WebAuthn. `Browser` and
  undocumented domains are unsupported. BROWSKI will use a narrower Rust-owned
  allowlist; Chrome version differences may remove methods or event behavior.
- Browser-restricted pages, extension pages, Chrome Web Store pages, and
  special schemes may not be scriptable or available for user-tab control.
  Do not make the extension a fallback automation runtime for these surfaces.
- Native Messaging installation, extension ID stability, OS-specific host
  registration, signing/updating, and support lifecycle add packaging work.
  The host is a privileged local process and is an attack surface.
- Out-of-process iframe handling depends on Chrome flat-target semantics;
  attachment is not recursively transitive and deep-frame coverage is not
  promised until Rust-side integration validates it.
- Native Messaging is not a network service or remote deployment channel.
  Remote/cloud runtime attachment is not included in this decision.
- `debugger` triggers a powerful permission warning. Chrome DevTools opening
  on an attached tab detaches the extension; enterprise policy may block
  attachment. The user must explicitly reattach after this conflict.
- A compromised extension, native host, or local process can expose tasks and
  browser data. Keep payloads minimal, validate every boundary, and avoid
  secrets in logs/storage.
- Broad host permissions create avoidable access and user-trust risk. Keep
  browser-site access out of the initial manifest.

## Official Chrome documentation

All sources below are official Chrome for Developers documentation, accessed
2026-10-06. The `chrome.debugger` reference was last updated 2026-10-05 UTC.
Other pages do not consistently expose an update date. Recheck API availability
and behavior against the supported Chrome minimum before implementation.

- [Manifest file format](https://developer.chrome.com/docs/extensions/reference/manifest)
- [Extension service worker lifecycle](
  https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
)
- [Use WebSockets in service workers](https://developer.chrome.com/docs/extensions/how-to/web-platform/websockets)
- [Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [chrome.debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger)
- [chrome.sidePanel API](https://developer.chrome.com/docs/extensions/reference/api/sidePanel)
- [chrome.tabs API](https://developer.chrome.com/docs/extensions/reference/api/tabs)
- [The activeTab permission](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab)
- [Declare extension permissions](https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions)
- [Cross-origin network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)
- [Manifest content security policy](
  https://developer.chrome.com/docs/extensions/reference/manifest/content-security-policy
)
- [chrome.offscreen API](https://developer.chrome.com/docs/extensions/reference/api/offscreen)
- [Content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)
