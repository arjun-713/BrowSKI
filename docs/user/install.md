# Install BROWSKI for local development

BROWSKI is not packaged as a supported end-user installer yet. The commands
below build the current Linux development checkout; they do not install a
Native Messaging host or enable attached-browser mode.

After installing the prerequisites, run `./scripts/setup.sh` from the
repository root to build Rust, Python bindings, and the unpacked MV3 extension.
The manual commands below show the same development setup in separate steps.

## Prerequisites

- Linux x86_64 (the only currently exercised platform)
- Python 3.12 or newer and `uv`
- Rust toolchain and `cargo`
- Node.js and npm for the extension
- Google Chrome or Chromium

## Build the runtime

From the repository root:

```sh
uv sync --project python --extra dev
cargo build --workspace
uv run --project python maturin develop --manifest-path crates/python-bindings/Cargo.toml
```

The development extra installs the Luna adapter and test tools, but does not
install Jev's optional cloud SDK.

The Python binding build requires a Rust compiler. Run `browski doctor` from
the Python environment to inspect local prerequisites. The doctor command does
not make provider requests.

## Build the extension

```sh
cd extension
npm ci
npm run build
```

Load `extension/.output/chrome-mv3` from `chrome://extensions` with Developer
mode enabled. The side panel connects through the Linux Native Messaging host
relay to `browski serve`, which starts the authenticated runtime. After
attaching a tab, the side panel can submit a task and show structured runtime
events. The full extension-driven demo and browser E2E acceptance flow remain
unvalidated.

After installing the Python package, the Linux Native Messaging registration
can be generated for the exact extension ID shown at `chrome://extensions`:

```sh
browski-install-native-host --browser chrome --extension-id <32-character-extension-id>
```

Use `--browser chromium` for Chromium, or `--manifest-directory` to write the
manifest to a selected user-owned directory. This registers the host relay for
the chosen browser and extension ID.

## Current limits

The managed Chromium runtime remains the usable browser path. API-backed Luna
tasks require a configured OpenAI key and make billable requests when run.
Attached-browser product flow, a one-command installer, macOS/Windows support,
and Chrome Web Store packaging are not complete.
