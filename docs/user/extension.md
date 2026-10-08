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

The extension reviews an active tab only after the user selects **Capture
active tab**, then requires **Confirm and attach**. It forwards only the
runtime's permitted CDP commands and events. Fixed internal Rust-owned
observer/executor scripts are allowed; arbitrary
methods, script evaluation, network access, cookie access, and browser-wide
targets are rejected. It does not request page host permissions or expose API
keys to page content.

## Runtime connection status

The Python Native Messaging relay, Linux per-user manifest installer, Rust
attached-browser transport, and authenticated local service are implemented.
The service connects the attached Rust session to the Python agent runtime and
supports task submission, lifecycle events, confirmation responses, and
pause/resume/stop controls. The complete Chrome-driven local demo and packaged
extension tests pass with deterministic provider responses. They validate the
software path, not live Luna quality. A request being sent is never shown as
a successful task.

For local bridge diagnostics, install the host manifest for the extension's
exact ID with `browski-install-native-host`, then start `browski serve`.
Connect the side panel, select and attach a tab,
then submit a task. See the known limitations in the
[roadmap](../development/roadmap.md) before using this as a production agent.

## Explicit form values

The current finite-action path can type a value only when the user task names
both the field and the value explicitly, using one of these forms:

```text
set "Full name" to "Alex Demo"
fill "Email address" with "alex@example.invalid"
type "Bengaluru" into "Preferred city"
```

The quoted field label must uniquely match an interactable semantic input's
accessible name. Unquoted values, ambiguous labels, and page-provided values
do not create typing actions. This is a small explicit grammar, not general
natural-language field interpretation. The task still passes through the
configured provider privacy mode; see [privacy modes](privacy.md).

## Owned supporting tabs

To authorize a new destination explicitly, use:

```text
open "https://example.com/supporting-page" in a new tab
```

Only credential-free HTTP(S) URLs are accepted. The session owns at most eight
tabs, including the original tab, and the agent can switch only among those
owned identities. Closing the original user tab is refused. Stop/disconnect
detaches debugger connections and leaves browser tabs open. Cross-origin
navigation invalidates the affected attachment; reattach explicitly. Popups
and arbitrary existing tabs are not automatically adopted.

## Explicit cross-tab text transfer

For a narrow cross-tab transfer, the task can name one source label and one
destination field:

```text
transfer "Reference code" from supporting page into "Reference code"
```

Luna may identify only a semantic ref for a visible, non-input element whose
accessible name exactly matches the source label. The runtime reads that
element's current text locally, rejects recognized credential/PII patterns,
and stores bounded provenance separately from legacy unverified facts. On a
later step, the value becomes a typing candidate only when exactly one
interactable destination input matches the requested label and the source tab
is still owned by the session. Multiple or missing matches abstain. Page text
remains untrusted data; the grammar authorizes copying one value, not following
instructions found in that value. Standard mode may send this task and page
evidence to the configured provider. Privacy-first applies its best-effort
redaction. This path is limited and is not a universal secret detector or a
general cross-page extraction feature.

See [extension architecture](../architecture/browser-extension.md) and
[protocol versioning](../protocols/versioning.md) for the current design and
wire contract.
