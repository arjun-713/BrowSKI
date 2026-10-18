# Browser extension

BROWSKI's Manifest V3 extension is a side panel and browser-session attachment
layer. It is not a separate browser agent: planning, semantic observation,
action execution, verification, and recovery remain runtime responsibilities.

## General and Fast (BROWSKI 2.0 migration)

Connect the local service, select General or Fast, and submit a task with a web
link or starting page. Fast defaults to CPU Laya with no paid inference; General
requires separately enabled OpenAI text inference and paid permission. Jev is an
optional Fast selection when credentials are available. Settings changes apply
to the next task and are refused during a run.

These engines open a separate task-owned browser profile; source tabs are
reference context and do not transfer cookies/login state or debugger control.
Current tools support navigation/reading. The expected URL/heading fields give
an independent navigation check; without one, DONE remains unverified. Progress,
pause/stop and final result counters use the existing Native Messaging bridge.
See [configuration](configuration.md), [debugging](debugging.md), and the
[migration checkpoint](../architecture/migration-status.md) for tested scope.

The attachment, explicit form values, owned supporting tabs, vision and checkpoint
features documented below apply to **Legacy** unless explicitly stated otherwise.
They have not all migrated to General/Fast. The new engines' navigation toolset
cannot bypass consequential-action approval by submitting forms.

## Build and load

```sh
cd extension
npm ci
npm run dev
```

For an unpacked production build, run `npm run build` and load
`extension/.output/chrome-mv3` through `chrome://extensions`.

On Linux, the `.output` directory is hidden. In Chrome's **Load unpacked**
folder chooser, press **Ctrl+L**, paste the full absolute path ending in
`extension/.output/chrome-mv3`, and press Enter. After rebuilding an installed
extension, use its **Reload** button on `chrome://extensions` and reopen the
side panel. The panel footer displays the installed manifest version.

The panel keeps the task composer and run controls at the bottom, with the
action timeline above. Connection, tab attachment, approval requests and errors
remain visible; configuration is under the collapsed settings section. The
orange accent indicates the working interface, not proof that a task succeeded.

The extension reviews an active tab only after the user selects **Capture
active tab**, then requires **Confirm and attach**. It forwards only the
runtime's permitted CDP commands and events. Fixed internal Rust-owned
observer/executor scripts are allowed; arbitrary
methods, script evaluation, network access, cookie access, and browser-wide
targets are rejected. It does not request page host permissions or expose API
keys to page content.

## Legacy attached-runtime connection status

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

## Legacy explicit form values

The current finite-action path can type a value only when the user task names
both the field and the value explicitly, using one of these forms:

```text
set "Full name" to "Alex Demo"
fill "Email address" with "alex@example.invalid"
type "Bengaluru" into "Preferred city"
```

The field label must uniquely match an interactable semantic input's
accessible name. Some unquoted assignments and uniquely grounded native option
names are supported too; ambiguous or missing values still abstain. Untrusted
page text alone cannot authorize a field value. This remains a bounded grammar,
not universal natural-language field interpretation. The task still passes
through the configured provider privacy mode; see [privacy modes](privacy.md).

## Legacy owned supporting tabs

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

## Legacy explicit cross-tab text transfer

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
