# ADR-014: Allow isolated transforms over semantic snapshot data

Date: 2026-10-08 · Status: accepted

This ADR amends ADR-011 only for bounded data transforms over a Rust-owned
semantic snapshot projection. Arbitrary model-authored code in the live page
realm remains disabled.

## Context

The M9 policy scaffold validates script and result limits but does not itself
isolate execution. Routing such scripts through page-realm CDP evaluation
would grant access to sensitive page data, browser APIs, and network paths.
ADR-011 therefore kept model-authored browser-code execution disabled.

Some deterministic extraction or aggregation operations can be expressed over
the semantic data BROWSKI already collected. They do not need DOM access or
browser mutation. This is a narrower capability than arbitrary browser code.

## Decision

- Permit a JavaScript function to transform only a bounded JSON projection of
  the current Rust-owned `SemanticSnapshot`.
- Evaluate the function in a fresh QuickJS runtime/context per request, with
  bounded source, input, execution time, engine heap, stack, and JSON output.
- Keep the session capability disabled by default and require explicit enablement.
- Register only the evaluation intrinsic needed to compile and run the
  supplied function. Use Rust's native JSON parse/stringify APIs for data
  transfer; do not expose a JavaScript `JSON` global.
- Register no host callbacks or module loader. Do not expose filesystem,
  process, shell, network, CDP, DOM, window, or browser-action APIs to the
  script. JavaScript `eval` remains within the same bounded runtime.
- Omit the URL, form summaries, input values, screenshots, and text excerpt
  from the input projection. Return the snapshot generation used by the
  transform.
- Omit text from text inputs, textboxes, searchboxes, comboboxes, sliders, and
  spinbuttons; redact credential-like element names/text before the JavaScript
  function receives the projection.
  This conservative rule is not a universal PII sanitizer; free-form page text
  can still contain sensitive data.
- Validate the JSON result against the Python-declared result schema before
  the agent can consume it. Apply the existing privacy boundary before any
  result is sent to a provider.
- Do not add this operation to the extension's generic CDP allowlist.
- Keep DOM inspection, page mutation, arbitrary browser-code execution, and
  extraction beyond the projection unavailable under ADR-011.

## Dependency and limits

The workspace declares Rust 1.78. `rquickjs` 0.9 and later require newer Rust
versions, so this implementation pins `rquickjs` 0.8.1, whose published
metadata declares Rust 1.65. Its wrapper default features are disabled;
module loading, dynamic loading, async, custom allocator, and host integration
features are not enabled. Only the minimum `Eval` intrinsic is registered;
module imports remain unavailable. The engine's memory cap relies on its default C
allocator; the rquickjs API documents that its memory limit is a no-op with
the custom allocator features.

Initial hard limits are 8 KiB source, 128 KiB projected input, 1.5 seconds of
execution, 4 MiB QuickJS heap, 256 KiB stack, and 16 KiB JSON output. The
projection includes at most 160 semantic elements and truncates projected
title/label/text strings to 160 characters. Changing these bounds requires
tests and a documented reason.

This is capability isolation within the process, not an operating-system
sandbox. A QuickJS native-engine vulnerability is not contained by a worker
process here; arbitrary DOM code is therefore still out of scope.

## Consequences

The agent may request JavaScript for deterministic operations on already-
collected semantic data through a fixed result schema, but this implementation
does not provide a browser DOM escape hatch. No browser state changes and no
new page data are available to the script. Session and Python policy gates
default to disabled.

The engine returns generation provenance. The Luna proposal and result
contracts, fixed-schema adapter, and disabled-by-default config key exist, but
the agent graph must not advertise or call this capability until session
factory wiring, safe trace events, and privacy inspection are connected.

## Validation

Rust tests cover ordinary transforms, infinite loops, heap exhaustion,
recursion, non-JSON output, oversized output, unavailable module imports,
absent browser/host globals, secret-field exclusion, snapshot generation, and
fresh-runtime isolation.
Python policy tests cover disabled defaults, capability budgets, normalized
trace categories, provenance envelope validation, result schema checks, and
malformed/oversized response handling. These tests do not establish safety
against native engine vulnerabilities or validate provider behavior.
