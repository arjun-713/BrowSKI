# Configuration

The CLI accepts a TOML configuration file with `--config`. The shipped
defaults are in `python/src/browser_agent/cli/default.toml`; copy that file to
a user-owned location before editing it.

The current policy defaults to:

- GPT-6 Luna as the active reasoning provider, model `gpt-6-luna`.
- Laya in shadow mode only; it must never select executable actions.
- Jev disabled.
- Standard privacy mode and confirmation for high-risk actions.
- Attached-browser task transport uses the Native Messaging runtime and shared
  browser core. The side panel can submit and control attached-tab tasks.
- On-demand vision disabled unless `[vision].enabled` is set to `true`.

Set `OPENAI_API_KEY` or `BROWSKI_OPENAI_API_KEY` in the local runtime's
environment, or configure the key in the extension Settings panel. The panel
sends it over the authenticated Native Messaging connection and the runtime
stores it in the operating system keyring. Do not place the key in a TOML
file, task trace, or page content. `browski doctor` checks whether a key is
configured without printing it and does not call OpenAI. If no usable OS
keyring is available, use the runtime environment variables instead.

To enable on-demand vision in standard privacy mode, add this section to the
copied TOML file:

```toml
[vision]
enabled = true
```

Vision captures a temporary viewport image only for an explicit visual task
that the semantic observation cannot answer. It does not store screenshots.
Vision is blocked in `privacy_first` and `offline` modes until screenshot
redaction is available.

Run `browski config` to inspect the effective non-secret settings. It reports
whether an API key is present without printing its value.

`browski serve` starts the authenticated Native Messaging runtime. It accepts
an optional `--config` TOML file and `--database` checkpoint path. Connect the
extension and attach a tab before submitting a task. The full browser-driven
demo and extension E2E flow remain unvalidated.

Configuration is still evolving; the extension currently edits only the API
key and Native Messaging auto-connect preference. Privacy-first processing
remains incomplete and is not a complete end-to-end privacy guarantee. Review
[privacy modes](privacy.md) before using sensitive page data.
