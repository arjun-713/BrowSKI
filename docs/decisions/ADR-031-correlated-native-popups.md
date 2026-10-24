# ADR-031: Correlate native link popups with an attached click

Status: Proposed; acceptance requires the existing A/B/C differential and
negative ownership regressions. Date: 2026-10-22.

## Reproduction

The unchanged `multi_tab` fixture passes managed Rust and fails through the
extension after clicking an actual `target="_blank"` link. Chrome creates a tab,
but ADR-016's explicit-create map cannot discover it. A real packaged Chrome
probe of the fixture's `rel="noreferrer"` link reports `Page.windowOpen` with
`userGesture=true`, the expected URL and source tab; `tabs.onCreated` separately
reports that same opener tab ID. The new tab's URL is initially empty. No model
inference is needed to reproduce this boundary.

## Bounded extension of ADR-016

Keep the existing single Rust engine, attachment consent, Native Messaging,
opaque identities, eight-tab cap, origin fences and approval rules. Add two
negotiated synthetic operations; no generic target discovery or permission is
added:

- `BROWSKI.tabs.preparePopup`: an owned opener session and credential-free
  HTTP(S) destination, read by Rust from the already resolved native anchor.
- `BROWSKI.tabs.finishPopup`: consume the one-use popup ID or cancel it after
  input failure. Return the same owned-tab metadata as explicit creation.

The Rust-owned fixed read accepts only native `_blank` anchors without a
`download` attribute. It runs after identity/interactability/hit testing. The
runtime still sends the actual trusted mouse input: it does not replace a click
with URL navigation, suppress page handlers, generate selectors or accept
provider-produced JavaScript.

One expectation is permitted per attachment. It expires in six seconds, covering
the existing five-second mouse-release bound without increasing global command
timeouts. It must match both Chrome's user-gesture window-open event and a newly
created tab with the owned opener identity. A second candidate, unexpected URL,
unowned opener, expired ID, reuse or changed attachment fails closed. Numeric
Chrome IDs stay inside the extension. Only finishing this runtime operation may
attach the correlated page and register fresh opaque IDs. It must still be on
the requested origin after attachment; cross-origin redirects are refused.

Cancellation, timeout or detach invalidates the expectation. A page that fails
validation is detached if this operation attached it; it is never closed merely
because adoption failed. Existing unrelated tabs and unsolicited popups remain
unowned. New native popup ownership is a transport attachment responsibility,
not a second observation, decision or verification implementation in TypeScript.

## Compatibility and evidence

The backend-ready message advertises the negotiated optional capability. Missing
capabilities preserve the old behavior rather than sending unknown commands.
New extension methods require a paired host upgrade. Native Messaging v1,
BrowserAction, SemanticSnapshot and PyO3 schemas are unchanged. Extension patch
version advances to 0.2.5. Rust transport additions have default implementations
for managed and test transports.

Measure against the existing unchanged differential suite and independent gold,
per [the evaluation plan](../benchmarks/evaluation-plan.md). Preserve the failing
before-result. Add negative tests for expiry, replay, conflicting candidates,
wrong opener/destination/gesture, tab cap, origin drift, cancellation and owner
loss. Run real attached observation/execution/verification and managed
regressions before claiming this repair passes. This is infrastructure evidence,
not a new autonomous model benchmark or a replacement-engine attachment claim.

## Sources

- [Chrome tabs API](https://developer.chrome.com/docs/extensions/reference/api/tabs):
  optional opener identity and initially unavailable created-tab URL.
- [Chrome debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger):
  source-tab command/event routing.
- [CDP Page events](https://chromedevtools.github.io/devtools-protocol/tot/Page/):
  browser-reported window-open destination and gesture metadata.

Reviewed 2026-10-22 and checked against actual packaged Chromium behavior.
