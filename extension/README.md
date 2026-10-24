# BROWSKI browser extension

This Manifest V3 extension provides a Chrome side panel, runtime-session UI,
risk-based approval controls, and browser transport bridges. It contains no task planning, provider calls, browser observation
semantics, action policy, verification, recovery, or memory logic.

## Development

Use Node.js and npm from this directory:

```sh
npm ci
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

## Agent panel

General/OpenAI is the default for side-panel tasks under
[ADR-032](../docs/decisions/ADR-032-panel-agent-in-user-tabs.md). Pressing Send
starts in the current user tab with existing logins; General has no attachment
step. Fast/Laya remains selectable with a managed task browser. Legacy explicit
attachment lives under Settings → Advanced. Engine and provider changes apply
to the next task.

The panel shows the task, public action labels and expandable step goals,
HTTP(S) page hosts, risky-action approvals with reason and expiry, and a final
answer. A separate verdict shows Verified or Not verified with its reason.
Steps, actions, model calls and duration come from the runtime. Older runtimes
fall back to their summary. This display never independently invents a verdict.

Settings includes model, credentials, paid usage, privacy, debug capture,
connection and About. General uses OpenAI API credits and sends page content
and, when needed, screenshots to OpenAI. Disabling paid usage prevents hosted
calls; providers never silently switch. Password/card entry, purchases, sending,
deletion and account/security changes require approval. Runtime policy owns
the classification and freshness checks.

History holds at most twelve result receipts for the open panel session.
Closing the panel clears this list. Run again restores the full submitted task
as a draft for review and Send; optional URL/heading checks must be reviewed
again. Results render text, simple lists and safe HTTP(S) links without HTML
injection. The panel follows the system light/dark theme and reduced motion.

## Protocol and host status

The extension protocol is currently v1. Messages use a protocol version,
typed message name, correlation/event ID, and payload. The extension rejects
unknown protocol versions/types and oversized messages. Native Messaging
access is bound by Chrome's registered host `allowed_origins` entry to the
installed extension ID; `host.hello` negotiates supported protocol versions.
The Python package supplies the Linux Native Messaging host installer and
runtime relay. Install the host for the extension ID shown in
`chrome://extensions`, then start `browski serve`; see
[`docs/user/extension.md`](../docs/user/extension.md). The side panel reports
connection and task state from runtime events, not from successful message
submission alone. Packaged Chromium tests cover native panel creation, real
transport/observation/execution/verification, task control, confirmations,
settings, synthetic-secret isolation and a full fixture-driven multi-tab demo.
Three bounded live Luna smoke runs also completed through the real side panel;
broader live task reliability remains unverified. See the
[validation ledger](../docs/debugging/extension-e2e-validation-report.md).

The Legacy debugger bridge requires the user to capture the active tab, review its
origin, then separately select **Confirm and attach** while Native Messaging
is connected. It records the selected tab and at most seven explicitly created
supporting tabs with opaque identities. It does not transfer ownership on
active-tab changes. Agent closure of the original user tab is refused.
Same-origin navigation events are forwarded. A cross-origin navigation, tab
close, runtime session change, or Chrome debugger detach ends the attachment
and requires an explicit new review and attach.

Only the command and event names in `src/protocol.ts` are forwarded. Incoming
command parameters are shape-checked and bounded. `Runtime.evaluate` accepts
only fixed Rust-owned browser-truth expressions; `Runtime.callFunctionOn`
accepts only fixed Rust-owned observer/executor templates with validated
arguments. Action values are sent as data, never inserted into source. `Network.*`,
arbitrary script execution, cookie access, generic target creation,
browser-wide targets, and unknown domains are rejected. Explicit synthetic
`BROWSKI.tabs.*` commands provide bounded owned-tab lifecycle operations;
see [ADR-016](../docs/decisions/ADR-016-extension-owned-tabs.md).
The Native Messaging host must negotiate an explicit subset of the
extension's method and event ceiling. Chrome command and event payloads
are relayed to the host without interpretation; this is transport plumbing,
not a TypeScript automation implementation.

The extension permissions are `sidePanel`, `nativeMessaging`, `storage`,
`activeTab`, `debugger`, and `tabs`. The `tabs` permission supports the explicit
mention picker (tab titles and URLs in the current window). A top-frame content
script runs on HTTP(S) pages solely to display the orange activity frame. It
does not collect page data, resolve targets, or execute browser actions.
These matches may cause Chrome to show a website-access permission notice.
See Chrome's [content-script documentation](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts).
Explicit tab-origin review may read
debugger target metadata for the selected tab when Chrome has not granted
`activeTab` URL access. Only the attachment's bounded ownership map can route
commands to supporting tabs.

## Sidebar composer and activity

- Draft a task in the bottom composer; **Enter** sends and **Shift+Enter** adds
  a line. Drafting is available before connecting and while another task runs.
- Type `/` or choose **Open shortcuts** for `/summarize`, `/extract`, and
  `/compare` task templates. `/pause`, `/resume`, and `/stop` appear only when
  the runtime permits that control. Arrow keys navigate; Enter selects;
  Escape dismisses. Choosing a template does not automatically send it.
- Type `@` or choose **Mention a tab or link** to search HTTP(S) tabs in the
  current window. Type `@https://example.org/path` to add a link directly.
  Mentions include only the selected title and URL on send; they do not read
  the other tab's contents or grant control of it. General starts from the active
  tab when Send is pressed; Legacy retains explicit attachment.
- Attach or drop `.txt`, `.md`, `.csv`, or `.json` files for text context.
  References are removable. Up to five references fit within the existing
  4,000-character total task limit; individual files must be at most 32 KB.
  Excess content is rejected with an explanation, never silently truncated.
  PDFs, images, and uploading files into websites are not implemented here.
- File contents and draft references stay in panel memory until sending. The
  runtime's normal task and privacy handling applies after sending. Closing
  the panel discards an unsent draft. Failed submissions preserve it.
- Activity separates public decision summaries, actions, and verification
  results. Expand a decision to inspect its safe summary. Hidden model
  reasoning is neither requested nor displayed.
- The orange edge and **BROWSKI is working** badge appear only on the owning
  session's tabs while it is running. They clear on pause, approval wait,
  completion, failure, stop, detach, and disconnection. They do not intercept
  pointer input and use a steady edge when reduced motion is enabled.

After reloading the extension, refresh any already-open task page once so its
activity script is loaded. Chrome's protected pages do not support the frame.
The generated manifest version is displayed under Settings → About.

### Validation scope

The relevant measurement plan is
[`docs/benchmarks/evaluation-plan.md`](../docs/benchmarks/evaluation-plan.md).
This presentation change is evaluated through panel component/contract tests
and fixture-driven browser previews, including reference selection and removal,
file context, send/stop, public details, approval expiry, result/verdict rendering,
light/dark themes, and narrow-panel overflow. Packaged Chromium lifecycle tests
remain a separate integration gate; previews do not establish live relay behavior. It does not alter provider routing or establish a change
in task success, token usage, model cost, or agent latency. Those claims require
a separate frozen task-mix evaluation under that plan.

## Browser E2E smoke

The opt-in Playwright smoke launches the built MV3 extension in bundled
Chromium, registers a temporary Native Messaging manifest for that extension
ID, connects to the real local runtime, and attaches/detaches the local demo
tab through Chrome's debugger API.

```sh
cd python
uv run --extra dev playwright install chromium
cd ..
make build
make test-extension-e2e
```

The E2E test is excluded from the normal pytest run unless the Make target sets
`BROWSKI_EXTENSION_E2E=1`. It covers the transport and attached-session
boundary and the full side-panel task flow with scripted provider responses.
It does not measure model performance or establish live provider availability.
The local pages are in `examples/demo_site/` and prevent server submission.

The harness installs its temporary host under the browser's custom profile
directory. For a manual browser launched with `--user-data-dir`, pass
`--manifest-directory <user-data-dir>/NativeMessagingHosts` to
`browski-install-native-host`. Chrome's
[Native Messaging documentation](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
describes this profile-specific lookup and the separate Chrome for Testing
default directory.
