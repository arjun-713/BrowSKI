# Configuration

The CLI accepts a TOML configuration file with `--config`. The shipped
defaults are in `python/src/browser_agent/cli/default.toml`; copy that file to
a user-owned location before editing it.

## Current engines and defaults

Fast/Laya is the default. The local CPU worker loads the prepared browser-tuned
checkpoint once per task; it does not need an HTTP Laya daemon or hosted key.
Text generation and paid inference are disabled by default. Keep other required
sections from the packaged TOML when copying it; this excerpt is not a complete file:

```toml
[agent]
orchestrator = "langgraph" # Legacy compatibility field; new engines bypass that graph
engine = "fast"           # fast, general, legacy
fast_provider = "laya"     # laya or optional hosted jev
text_provider = "disabled" # disabled or explicit OpenAI
allow_paid_api = false
text_model = "gpt-6-luna"
laya_checkpoint = "/absolute/path/to/mango/.browser-data/laya-browser-v19s"
jev_endpoint = "https://api.typesafe.ai/v1/systemone"
```

General uses the official Browser Use Agent and needs `text_provider = "openai"`,
`allow_paid_api = true`, an OpenAI key and standard privacy mode. Jev needs
`fast_provider = "jev"`, paid permission, standard privacy mode and
`TYPESAFE_API_KEY` in the runtime environment. Missing permission or credentials
blocks the task and identifies local Laya as an alternative; it never enables a
fallback. Live Jev is not yet validated. Local generative models are disabled on
this machine by user instruction; Laya is not an arbitrary text generator.

Set `OPENAI_API_KEY` or `BROWSKI_OPENAI_API_KEY` in the runtime environment, or use
the extension's OS-keyring form. Never put keys in TOML, task text or logs. Key
presence does not authorize paid requests. Doctor reports safe metadata only,
without inference or hosted-provider connectivity checks.

The sidebar selects General/Fast and Laya/Jev for the next task. Settings expose
text provider/model, paid permission, checkpoint/endpoint, privacy and trace level.
Changes are refused during a task; no mid-action provider switching occurs.
General/Fast use separate task-owned browser profiles, not the attached source
session. Sidebar Fast supports links and approved quoted-literal ordinary text,
native date and single-select fields. It validates actual values and native
constraints; ambiguous options and unsupported custom controls stay unverified.
One quoted named click may follow verified fields, with a separate approval and
fresh final URL/heading checks. Without discriminating outcome criteria it blocks;
after the click it only reads for the receipt, without repeating submission.
Fast can open supporting tabs through links and select task-owned HTTP tabs on
the allowed host. It verifies focus using full browser target identities and
refuses more than eight tabs. General can also select an owned HTTP tab. These
tabs belong to the isolated task profile; this does not import personal tabs,
authentication or values from supporting pages into fields.
Sidebar General also offers approved click and
quoted-literal text entry; CLI without an approval sink remains read-only.
The product General budget is four hosted requests, five steps and 90 seconds
for the Agent run; the explicit `general` CLI command defaults to three requests.
Paid permission is still required. Without supported independent
URL/heading criteria, model DONE is unverified. See the [migration checkpoint](../architecture/migration-status.md).

Standard mode permits explicitly opted-in hosted inference. Privacy-first and
offline block the new hosted adapters; local Laya remains available. These modes
do not turn ordinary webpage loading into an air-gapped browser. Debug capture
is independently opt-in under `[debug]`; [debugging](debugging.md) documents its
bounds, redaction and replay behavior.

## Legacy-only settings

Choose `agent.engine = "legacy"` explicitly to use the retained Rust/LangGraph/Luna
route. Its paid reasoner and optional vision also require paid permission.
`reasoning.effort`, `decision.mode`, `decision.shadow_telemetry`, `[vision]` and
`[browser_code]` belong to that route. Legacy Laya remains a non-executing shadow;
this is distinct from the new executable CPU Fast provider. High-risk Legacy
actions still require approval. Broader forms, source-to-field transfer and encrypted
checkpoints remain Legacy features until migrated and validated.

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
extension. Attach a source tab only for Legacy; General/Fast open their own browser. Browser-driven software
tests and the complete local demo use deterministic provider fixtures. Limited
live Luna fixture tasks are measured in the
[repair smoke report](../development/live-agent-repair-2026-10-12.md); public-site
reliability remains unverified.

The Legacy shadow Laya endpoint defaults to `http://127.0.0.1:8001`. Configure another
endpoint in `[decision].laya_endpoint` if needed. It remains shadow-only and
does not delay Luna's executable decision.

Trusted website names for user-requested shopping tasks are configured locally:

```toml
[navigation.site_aliases]
amazon = "https://www.amazon.in/"
flipkart = "https://www.flipkart.com/"
apple = "https://www.apple.com/in/shop/"
```

This optional section replaces the default mappings when supplied. Destinations
must be credential-free HTTP(S) URLs without queries or fragments. Naming a
site authorizes navigation only in a browsing/shopping instruction; page text
cannot add destinations. These aliases make tabs available to Luna, but do not
guarantee retailer availability, account access, or successful product filtering.

Configuration is still evolving. The extension edits the engine settings listed
above, the API key through the OS keyring, and the local Native Messaging
auto-connect preference. Privacy-first processing remains incomplete and is
not a complete end-to-end privacy guarantee. Review
[privacy modes](privacy.md) before using sensitive page data.
