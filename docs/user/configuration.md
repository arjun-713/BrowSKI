# Configuration

The CLI accepts a TOML configuration file with `--config`. The shipped
defaults are in `python/src/browser_agent/cli/default.toml`; copy that file to
a user-owned location before editing it.

The current policy defaults to:

- GPT-6 Luna as the active reasoning provider, model `gpt-6-luna`.
- Laya in shadow mode only; it must never select executable actions.
- Jev disabled.
- Standard privacy mode and confirmation for high-risk actions.
- Native Messaging is the default extension transport; the side panel submits
  tasks into the shared runtime and browser core.
- Reasoning effort defaults to low; the extension can select none or low.
- On-demand vision disabled unless `[vision].enabled` is set to `true`.
- Local debug capture disabled unless `[debug].enabled` is set to `true`;
  see [local debug sessions](debugging.md) for storage and redaction details.

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

The extension Settings panel reads and updates only default reasoning effort,
privacy mode, Laya comparison mode, and trace detail. Laya can be disabled or
run in shadow mode, where it never selects or executes browser actions. High-risk
confirmation remains required and cannot be disabled in the panel. Browser
transport is shown read-only and remains managed by CLI configuration.

Settings changes are validated by the local runtime, written atomically to the
selected TOML file with owner-only file permissions, and apply to the next task.
The panel cannot change them while a task is active. With an explicit `--config`
or `BROWSKI_CONFIG`, that file is updated. Otherwise, extension changes use
`$XDG_CONFIG_HOME/browski/config.toml`, or `~/.config/browski/config.toml` when
`XDG_CONFIG_HOME` is unset. Once created, that file becomes the effective user
configuration. Settings updates do not make provider requests.
If the current CLI configuration disables trace detail (`traces.level = "off"`),
the panel reports that state and asks you to select `standard` or `detailed` in
the CLI configuration before using its settings controls.

`browski serve` starts the authenticated Native Messaging runtime. It accepts
an optional `--config` TOML file and `--database` checkpoint path. Connect the
extension and attach a tab before submitting a task. Browser-driven software
tests and the complete local demo use deterministic provider fixtures; live
Luna inference and task reliability remain unverified.

Configuration is still evolving. The extension edits the settings listed
above, the API key through the OS keyring, and the local Native Messaging
auto-connect preference. Privacy-first processing remains incomplete and is
not a complete end-to-end privacy guarantee. Review
[privacy modes](privacy.md) before using sensitive page data.
