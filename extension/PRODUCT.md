# BROWSKI browser companion

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A person assigning a browser task while watching their own Chrome tabs. The side
panel keeps the requested task, public progress, approvals and final answer
visible beside the browser.

## Product Purpose

Find, read and act in the browser with independent outcome verification and
explicit user approval before risky actions. The panel is the conversation and
control surface for the local BROWSKI runtime.

## Capabilities and Constraints

- Production UI is the WXT/React extension in `mango`; no provider calls or agent
  decision logic run in React.
- ADR-032 governs side-panel General tasks: General/OpenAI is the default, starts
  from the user's current Chrome tab and uses the user's existing logins. Send
  is consent to begin; no attach step. Ending the lease leaves user tabs open.
- Fast/Laya remains selectable and uses its managed task browser. Legacy remains
  under Advanced with explicit origin review and attachment.
- Risky actions pause for approval: payment/purchase, send/post/publish, deletion,
  account/security changes and sensitive password/card entry. Cards show the
  public reason and expiration. Runtime freshness enforcement remains authoritative.
- General paid usage sends page content and sometimes screenshots to OpenAI and
  consumes API credits. Paid usage and privacy settings remain explicit. There
  is no silent provider fallback.
- A completion claim alone does not establish success. Results show the runtime's
  independent verdict and reason, answer and bounded counters. Older runtimes
  fall back to their summary and verified outcome status.
- The composer preserves slash shortcuts, selected tab/link references and
  TXT/Markdown/CSV/JSON text files. Five references and the total 4,000-character
  task limit remain. Mentions share title/URL context; they do not expose the
  contents of arbitrary tabs. PDF/image interpretation and website file uploads
  are outside this UI capability.
- Public step goals are visible and expandable; hidden reasoning is never shown.
- Drafts and up to twelve recent result receipts stay in panel memory. Closing
  the panel clears them. Run again restores a draft for review and sending.
- UI fixtures and screenshots validate presentation and controls, not live-model
  reliability or correct completion of arbitrary tasks.

## Brand Commitments

A refined browser companion comparable in interaction density to Comet, Claude
for Chrome and Arc. Warm orange remains the sending and activity accent. The
surface follows light/dark system preference, supports narrow Chrome panels,
and keeps the task and composer ahead of implementation details.

## Evidence on Hand

[`ADR-032`](../docs/decisions/ADR-032-panel-agent-in-user-tabs.md) records the user
choices. `src/protocol.ts` defines additive panel messages. Panel tests cover
composer controls, approvals, results, verdicts and connection states. Browser
previews use fake transports and synthetic snapshots. Installed-Chrome relay
and live task acceptance require their separate integration gates.
