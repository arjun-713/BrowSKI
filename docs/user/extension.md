# Browser extension

BROWSKI's Manifest V3 extension is a side panel and browser-session attachment
layer. It is not a separate browser agent: planning, semantic observation,
action execution, verification, and recovery remain runtime responsibilities.

## Build and load

```sh
cd extension
npm ci
npm run dev
```

For an unpacked production build, run `npm run build` and load
`extension/.output/chrome-mv3` through `chrome://extensions`.

The extension requests an active tab only after the user selects **Attach
active tab**. It forwards only documented CDP command and event names. Unknown
methods, script evaluation, network access, cookie access, and browser-wide
targets are rejected. It does not request page host permissions or expose API
keys to page content.

## Runtime connection status

The Python Native Messaging relay, Linux per-user manifest installer, Rust
attached-browser transport, and authenticated local service are implemented.
The service connects the attached Rust session to the Python agent runtime and
supports task submission, lifecycle events, confirmation responses, and
pause/resume/stop controls. The complete Chrome-driven demo and extension E2E
acceptance flow remain unvalidated. A request being sent is never shown as a
successful task.

For local bridge diagnostics, install the host manifest for the extension's
exact ID with `browski-install-native-host`, then start `browski serve`. This
After starting `browski serve`, connect the side panel, select and attach a tab,
then submit a task. See the known limitations in the
[roadmap](../development/roadmap.md) before using this as a production agent.

See [extension architecture](../architecture/browser-extension.md) and
[protocol versioning](../protocols/versioning.md) for the current design and
wire contract.
