# Executor

The executor crate defines typed `BrowserAction` values, structured execution
failures, and evidence-bearing outcomes. `browser-core` performs the actions
against a live session and coordinates deterministic verification.

Supported actions include click, type, select, check, hover, press, scroll,
navigate, back, forward, reload, new tab, tab activation, tab close, dialog
handling, and an explicit wait utility. Element-targeted actions require an
`ElementRef`; they do not accept model-generated selectors or backend node
identifiers.

File upload is deferred. The current action contract has no constrained file
chooser or authorized-path capability, so adding a raw path field would expose
an unsafe and incomplete boundary. Support should be added only with an
explicit file authorization policy and browser-side verification.

The executor does not perform agent reasoning or LLM calls. A completed CDP
command is not treated as verified action success; see the `verification`
crate.
