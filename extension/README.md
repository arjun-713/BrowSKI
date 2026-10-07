# BROWSKI browser extension

This Manifest V3 extension provides a Chrome side panel, runtime-session UI,
explicit approval controls, and a narrowly scoped active-tab debugger message
bridge. It contains no task planning, provider calls, browser observation
semantics, action policy, verification, recovery, or memory logic.

## Development

Use Node.js and npm from this directory:

```sh
npm install
npm run dev
npm run build
npm run test
npm run check:types
npm run lint
```

Load the unpacked output from `.output/chrome-mv3` using `chrome://extensions`.
The toolbar action opens the side panel. The panel connects to the Native
Messaging host `com.browski.runtime` when requested by the user, or when the
non-sensitive auto-connect preference is enabled.

## Protocol and host status

The extension protocol is currently v1. Messages use a protocol version,
typed message name, correlation/event ID, and payload. The extension rejects
unknown protocol versions/types and oversized messages. Native Messaging
access is bound by Chrome's registered host `allowed_origins` entry to the
installed extension ID; `host.hello` negotiates supported protocol versions.
This repository does not yet contain a registered native host or a runtime
relay, so the panel reports a host error and task controls remain unavailable
until an external host implements this contract. The UI never treats a sent
request as task success.

The debugger bridge requires the user to capture the active tab, review its
origin, then separately confirm **Attach reviewed tab** while the Native
Messaging protocol is ready. It records one owned tab, does not follow
active-tab changes, and detaches when the user requests it or the tab closes.
Same-origin navigation events are forwarded. A cross-origin navigation, tab
close, runtime session change, or Chrome debugger detach ends the attachment
and requires an explicit new review and attach.

Only the command and event names in `src/protocol.ts` are forwarded. Incoming
command parameters are shape-checked and bounded. `Runtime.evaluate`,
`Runtime.callFunctionOn`, `Network.*`, arbitrary script execution, cookie
access, target creation, browser-wide targets, and unknown domains are
rejected. The Native Messaging host must negotiate an explicit subset of the
extension's method and event ceiling. Chrome command and event payloads
are relayed to the host without interpretation; this is transport plumbing,
not a TypeScript automation implementation.

The default extension permissions are `sidePanel`, `nativeMessaging`,
`storage`, `activeTab`, and `debugger`. No content scripts, website host permissions,
provider keys, or page JavaScript are used.
