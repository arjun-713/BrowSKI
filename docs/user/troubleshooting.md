# Troubleshooting

## Runtime unavailable

Run `browski doctor` in the same Python environment used to start BROWSKI. It
checks the Rust binding, browser executable, configuration, local database,
extension host metadata, and Laya health without making an OpenAI request.

## Extension is disconnected

The extension requires `browski serve`, the registered Native Messaging host,
and a matching extension ID. Confirm the host path and extension ID with
`browski doctor`, then reconnect from the side panel. Rebuild the unpacked
extension after changing its protocol version.

## Debugger attach failed

Close DevTools or another debugger attached to the tab, then explicitly attach
again from the side panel. BROWSKI does not silently switch to another tab.
The attached-browser runtime requires the extension to remain connected while
the task is active.

## Chromium cannot start

Check that Chrome or Chromium is installed and executable. Managed-browser
mode launches a separate browser instance; attached-browser mode requires the
Native Messaging host and supported debugger methods.

## OpenAI key or request error

Configure the key in the side-panel Settings or set `OPENAI_API_KEY` or
`BROWSKI_OPENAI_API_KEY` in the runtime environment. The UI and doctor show
presence only. If keyring access fails, use the environment override.
Network and API errors are intentionally sanitized in normal user output;
developer logs identify error types without including request payloads.
For opt-in, sanitized request and response capture, see
[local debug sessions](debugging.md).

## Laya is unavailable

Laya health is relevant only to shadow comparison. It is not an active action
provider; an unavailable shadow service must not prevent Luna from choosing or
executing an otherwise valid action.

## Native Messaging host missing or protocol mismatch

Install the host with `browski-install-native-host` using the exact ID shown
in `chrome://extensions`, then start `browski serve`. The extension refuses
unknown protocol versions and keeps task controls unavailable when host
negotiation fails. The attached-browser backend shares the runtime's semantic
observation and execution path; it is not a separate extension agent.
