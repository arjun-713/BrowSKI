# Attached Chrome Step 0 incident

Status: the observation failure is reproduced and repaired. The user's
reattached Google tab passes authenticated CDP and DOM observation probes with
the rebuilt Rust binding and extension 0.1.6. Autonomous task completion remains
a separate acceptance gate.

## Checkout and scope

The requested `Projects/Browski` path was absent. The user explicitly selected
the existing `Projects/mango` implementation checkout. The sibling screenshot
benchmark remains an experiment; no production code is added there.

## Observed sequence

| Boundary | Evidence |
| --- | --- |
| User submits task in panel | `task.received` exists in both ignored local run logs |
| Authenticated relay and task creation | Stable run ID reaches Python and `RunStarted` |
| First graph observation | Retry traceback enters `observe_node`, `BrowserSession.observe`, `asyncio.to_thread` |
| Native observation | `RuntimeError` is raised inside the native thread; `_require_open` is absent from the traceback |
| Provider | No request recorded; these runs spent no model credits |
| Action / verification | Not reached |
| Termination | Runtime `RunFailed` and service result are presented as two failure entries |

Runs (raw logs are intentionally ignored and owner-only):

- `96ff39f1-f265-4187-b040-aedbfaa370e1`: received
  2026-10-15 18:47:57 UTC; first observation fails around 18:48:01 UTC.
- `c4adaf68-9466-4275-8114-837cd10551c4`: received
  2026-10-15 20:05:27.812 UTC; run starts 20:05:28.485 UTC;
  first observation fails 20:05:29.507 UTC.

The first capture had only the exception class. Commit `66f2a7b` added private-safe
traceback locations. The retry localizes the failure, but the old PyO3 mapper
discarded Rust's error variant. Exception text is not a safe substitute: browser
and provider errors can contain private content.

## Separate confirmed defects

1. Native browser errors lose their typed category at the Python boundary.
2. Observation has a completed event but no start event, hiding the active phase.
3. Debug records use the attachment ID for receipt and an independent runtime
   session UUID thereafter. Wire events rewrite the ID, making wire and local
   traces disagree.
4. Runtime and service terminal events duplicate one failure in the timeline.
5. Existing doctor inspects socket files; it cannot establish attached-browser
   readiness.

These defects explain the poor diagnostics. They do not yet explain why the
native observation failed on the user's tab.

## Reproduction controls

- Managed Chromium observation of Google succeeded without a provider.
- A fresh explicitly attached Google tab in packaged Chromium also succeeded.
- Navigating an attached local fixture to another origin intentionally detaches
  the session. Reusing that closed wrapper produces a different traceback
  (`_require_open`), so it is not the recorded native failure.
- The origin-consent boundary must remain enforced.

## Regression and acceptance

The deterministic reliability and differential suites exercise the real Native
Messaging extension, Rust observation/execution and verification. Their results
are tracked in the [validation report](extension-e2e-validation-report.md).
The production tab must additionally pass an authenticated read-only CDP probe
and observation after the diagnostic binding is installed. No paid inference is
needed for that investigation.

Do not mark the exact incident resolved until its actual native category is
captured, reproduced, corrected and regression-tested.

## October 16 reproduction and repair

Run `c82c7115-5aa0-4141-980a-64afda3bf922` with extension 0.1.5
failed between 12:53:17.824 and 12:53:18.829 UTC. Its preserved native
category is `CONNECTION_LOST`, operation `observe`. No provider request or
action preceded the error. An authenticated doctor probe on the user's
reattached Google tab then passed `Page.getLayoutMetrics` but failed DOM
observation with the same category.

The attached transport discarded errors returned by `read_frame`. A controlled
page with 80 nested component wrappers reproduced the failure through the real
packaged extension. `DOM.getDocument` returned only 15,571 bytes, but its JSON
depth was 171. The default Rust JSON parser limit was 128. The rejected frame
terminated the reader and all pending observations received `ConnectionLost`.
The small earlier fixtures did not exercise this transport limit.

The fix retains the 8 MiB frame bound, checks nesting before parsing with a
256-level cap, and uses stack-safe parsing within that bound. Malformed,
trailing and excessive-depth JSON remain rejected. Parser errors now reach
pending commands as fixed safe categories rather than private parser text.

The permanent `test_deep_dom_e2e.py` regression failed before the repair and
passed afterward in 19.03 seconds: panel submission, semantic observation,
bounded fixture decision, Rust click, deterministic verification and displayed
completion all execute through Native Messaging. The user's same Google tab
subsequently passed CDP, DOM observation and graph readiness using doctor.
That before/after result supports the repair; no raw DOM from the user's page
was captured, so its exact nesting depth is not asserted.

## Separate stale-extension protocol failure

Extension 0.1.4 rejected newly added observation-start trace events, marked
protocol negotiation incomplete, and kept a native port alive that no longer
forwarded CDP. This caused a distinct 30-second command timeout in run
`13140c3a-4756-435c-9240-ef8b2bded3c8`. Rebuilding 0.1.5 corrected
that mismatch. Version 0.1.6 also ignores bounded unknown diagnostic event
kinds and closes the port on malformed authoritative messages. Commands,
session ownership and approvals still require their strict existing schemas.

## Subsequent local provider-context rejection

After the transport repair, run `764cd96d-e2cc-480b-b259-ccd2b7bdbd19`
successfully observed the user's Google page (442 snapshot elements, about
7.2 seconds), then failed before contacting OpenAI. The local
`ProviderBoundary` rejected an oversized reasoning context within about 60 ms.
Its 32,000-character limit was being applied to the entire semantic inventory.
The UI incorrectly described that local error as unavailable Luna reasoning.

The provider boundary now projects the observation within the existing limit.
It preserves task constraints, memory, candidate options, browser checks,
typed candidate targets, source-bound evidence, focus, and ancestor context.
Remaining space is filled using the existing task relevance ranking. Retained
element records are unchanged, document order is preserved, and the outbound
observation is explicitly marked truncated. The complete local observation
continues to govern target binding, execution, and verification.

Required context that cannot fit still fails closed with a specific message
stating that no API request was sent. Safe debug metadata records original
and outbound character/element counts without recording raw private context.
This backend-only change does not require an extension version increment.

Regression coverage includes projection limits, immutable local context,
typed target and evidence retention, both standard and privacy-first modes,
and the user-visible error category. The crowded-page extension regression
uses the real provider boundary with deterministic decisions; it does not
establish live Luna task success or retailer task completion.

## Separate connection lifetime limit

The crowded-page regression subsequently reached the legacy bridge's
4,096-message replay budget. CDP results consumed that budget even with only
one browser action. The recorded rejection was exactly
`extension message replay window is exhausted`, explaining another apparent
browser disconnection after observation had succeeded.

Extension 0.1.7 and the paired runtime now use strictly increasing outbound
message sequences with a bounded recent UUID cache. The successful diagnostic
completed observation, click, verification and displayed task completion after
9,978 messages, with 4,096 IDs retained. See
[ADR-021](../decisions/ADR-021-sequenced-extension-sessions.md) and the
[validation ledger](extension-e2e-validation-report.md) for the measured latency
and remaining acceptance gaps.
