# Install BROWSKI locally on Linux

The source installer builds a checkout-local BROWSKI environment and the
unpacked MV3 extension. It supports Linux x86_64, the platform currently
exercised by the project. It does not install packages globally, register a
Native Messaging host, write browser settings, or create or edit API keys.

## Requirements

- Linux x86_64
- Python 3.12 or newer and `uv`
- Rust stable toolchain (`rustc` and `cargo`)
- Node.js 22 or newer and `npm`
- Google Chrome or Chromium

Set `CHROME_PATH` if the browser binary is not on `PATH`:

```sh
export CHROME_PATH=/absolute/path/to/chrome
```

## Check prerequisites

From the repository root, run the read-only preflight:

```sh
./scripts/install.sh --preflight
```

It checks the operating system, architecture, tool versions, and browser binary.
It creates no files. Use `./scripts/install.sh --help` to see installer options.

## Build the local runtime and extensions

```sh
./scripts/install.sh
```

The installer uses the existing lockfiles and keeps its dependencies in the
checkout: Python's `python/.venv`, Cargo's `target/`, and the extension's
`extension/node_modules/`. The Rust workspace and PyO3 bindings use optimized
release builds for the installed runtime. Developer commands such as
`make bindings` still build the development profile. WXT creates both
extension outputs:

| Build | Output directory | Use |
|---|---|---|
| Development | `extension/.output/chrome-mv3-dev` | Load as an unpacked extension while developing |
| Production | `extension/.output/chrome-mv3` | Load as the regular optimized build |

Load one output from `chrome://extensions` with Developer mode enabled. Copy
the exact extension ID shown on that page; development and production builds
may have different IDs. The extension-driven software flow is covered by
packaged Chromium tests with deterministic provider responses. Limited live
Luna tasks also pass; see the [repair smoke report](../development/live-agent-repair-2026-10-12.md).
This does not establish broad public-site task reliability.

Use the checkout-local commands so the runtime does not need a global install:

```sh
uv run --project python browski --help
uv run --project python browski doctor
```

`browski doctor` inspects local prerequisites and loopback service health. It
does not run model inference or make external provider requests. A task that
uses GPT-6 Luna requires an OpenAI key and can incur API charges.

## Register the Native Messaging host for a browser profile

Registration is a separate, explicit step. It writes only BROWSKI's named
launcher and manifest into the directory you select. It does not edit browser
preferences or API-key files. Supply the exact 32-character extension ID
shown by Chrome or Chromium. Run these commands from the repository root,
and set `BROWSKI_CHROME_PROFILE` to the browser's user-data directory:

```sh
export BROWSKI_CHROME_PROFILE=/absolute/path/to/browser-user-data
uv run --project python browski-install-native-host \
  --browser chrome \
  --extension-id <exact-extension-id> \
  --host-executable "$PWD/python/.venv/bin/browski-native-host" \
  --manifest-directory "$BROWSKI_CHROME_PROFILE/NativeMessagingHosts"
```

For a custom browser launch such as
`chrome --user-data-dir=/path/to/profile`, use `/path/to/profile` here. The
browser reads user-level Native Messaging manifests from the
`NativeMessagingHosts` directory inside that profile. For a default Chrome
profile on Linux, the corresponding directory is usually
`$HOME/.config/google-chrome/NativeMessagingHosts`; for Chromium it is usually
`$HOME/.config/chromium/NativeMessagingHosts`. Use `--browser chromium` for
Chromium. Do not point `--manifest-directory` at an arbitrary folder: the
browser must search that directory for the manifest.

The installer validates the exact extension ID and atomically writes the
BROWSKI host wrapper and manifest. Re-running it updates those two BROWSKI
files for the supplied ID. If registering another build, copy that build's ID
and run the command again. Close and reopen the browser after registration,
then start the local bridge in another terminal:

```sh
uv run --project python browski serve
```

To start the installed local CPU Laya server and the extension backend together:

```sh
./scripts/start-local.sh
```

The launcher reuses Laya when port 8001 is already listening, waits for its
health check, and starts the authenticated backend. It uses the existing
Laya installation in the sibling `Agent-Browser-Benchmark/.venv` by default;
set `LAYA_SERVE_BIN` for another installed launcher. Model files must already
be cached locally. Logs are written under `~/.local/state/browski`, or
`$XDG_STATE_HOME/browski`. Keep the terminal open; Ctrl+C stops the services
started by that invocation. Start only one backend launcher at a time.

The backend launcher accepts the existing OpenAI environment variables or OS
keyring. It also reads `OPENAI_API_KEY` / `BROWSKI_OPENAI_API_KEY` from a local
checkout `.env` file, if present and no environment key is set. That file must
be owner-only (`chmod 600 .env`); it is read as data, never sourced as shell
commands. The key is passed only to the backend, not the Laya server. Never
commit this file.

Attach a tab in the extension side panel before submitting a task. The
attached-browser route and complete local demo have fixture-backed browser
acceptance tests. They do not establish autonomous model reliability.

## Manual setup

The installer uses the same existing tools as these commands, if you prefer to
run each build step manually:

```sh
uv sync --locked --project python --extra dev
cargo build --workspace
cd python && uv run maturin develop
npm --prefix extension ci
npm --prefix extension run build -- --mode development
npm --prefix extension run build -- --mode production
```

The Python development extra includes the Luna adapter and local test tools;
it does not install Jev's optional cloud SDK. Building makes no provider
requests; doctor checks local service health without model inference or
external provider requests.

## Current limits

This is a local source-checkout setup, not a system package or signed
browser-store distribution. The installer does not set up other platforms,
services that start automatically, or browser policy. Screenshot redaction
and complete PII detection remain unavailable; see
the [roadmap](../development/roadmap.md).
