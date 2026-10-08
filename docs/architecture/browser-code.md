# Controlled semantic-data transform boundary

BROWSKI's normal interaction path remains semantic browser observations and
typed `BrowserAction` values executed and verified by the Rust browser core.
Browser code is an exceptional data transform over one Rust-owned semantic
snapshot. It does not control the page and cannot replace normal browser
actions.

## Capability and boundary

The Rust `browser-agent-code` crate evaluates a JavaScript function in a fresh
QuickJS runtime for each request. Its only input is a bounded JSON projection
built from the session's current `SemanticSnapshot` inside Rust. The
projection carries the snapshot schema version and generation, title, and
bounded semantic element labels, text, state, visibility, and document order.
It omits URL, screenshots, form summaries, all typed values, and page text
excerpts. Text from text inputs, textboxes, searchboxes, comboboxes, sliders,
and spinbuttons is omitted. Credential-like labels and text are conservatively
replaced before they reach JavaScript. Free-form page text can still contain
sensitive data; this local capability does not claim universal PII
sanitization. The `truncated` flag reports when the projection omits elements
past its element cap.

The function receives one argument, `snapshot`, and must return a JSON value.
The output is bounded JSON paired with the source snapshot generation. Python
validates the output against the declared result schema before it can be used.
The binding obtains a fresh Rust observation before constructing this input.
It does not mutate the page and reports the exact generation used for the
computation. The graph refuses a result if the subsequent observation changes
the decision state.

The session capability defaults to disabled. When explicitly enabled, source
bytes, input bytes, execution time, engine heap, stack, and result bytes have
hard limits. Each call receives a new runtime and context, so globals do not
persist between calls. The evaluator registers only the evaluation intrinsic
needed to compile and run the supplied function. Rust uses QuickJS's native
JSON parse/stringify helpers to transfer data, so the script has no `JSON`
global. Evaluation does expose JavaScript `eval` inside that same bounded
runtime. It does not register Rust callbacks, filesystem/process/network APIs,
dynamic module loading, or browser objects. The environment has no
`document`, `window`, `fetch`, `process`, `require`, `std`, or `os` global.

The evaluator never receives a CDP session, element handle, or browser action.
It cannot inspect additional page state or change page state. For DOM
manipulation, interaction, or extraction requiring data absent from the
semantic projection, use semantic actions/observation or keep the task
unavailable. A page-realm CDP evaluator is not an implementation of this
capability.

## Privacy and traces

Page-derived labels and text remain untrusted. The existing privacy boundary
must inspect results before they enter a Luna request. The transform does not
authorize external disclosure.

The safe trace envelope uses fixed purpose and reason categories, source
digest, source byte count, configured limits, result-schema name, duration,
and outcome. These events exclude source code, page
text, raw reason/purpose strings, and result contents. The script digest is
diagnostic metadata, not a replacement for source confidentiality.

## Agent contract and implementation status

The bounded Rust transform engine, session-owned PyO3 helper, typed Luna
proposal/result contract, fixed result schema, Python tool adapter, and
off-by-default configuration key are implemented. The graph dispatches the
capability only when explicitly enabled, emits safe start/completion events,
and passes its bounded output through the provider privacy boundary. Output
is held for one subsequent decision and cleared on pause, stop, stale state,
or runtime shutdown. Scripts and results are excluded from checkpoints.
Cancellation joins the bounded native worker before releasing its owner;
it cannot interrupt a Python worker thread immediately.

See [ADR-014](../decisions/ADR-014-isolated-semantic-data-transforms.md) for
the bounded exception to [ADR-011](../decisions/ADR-011-browser-code-remains-disabled.md).
ADR-011 continues to govern model-authored browser code that would access or
mutate the live page.
