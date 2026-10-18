# ADR-025: Task-local approval for managed browser interactions

Date: 2026-10-18 · Status: accepted, bounded General form slice

## Problem

The new General engine exposed only navigation/read tools. The existing sidebar
approval card and Native Messaging messages resumed Legacy graph checkpoints;
managed tasks could not wait for a user decision. Simply enabling upstream click
and input tools would bypass that product guarantee.

## Decision

Reuse the existing card and wire messages. A task-local `TaskControl` owns one
pending future with a unique approval ID. The service validates the session and
pending ID, resolves that future, and resumes the same engine task. It never
creates a second executor. Approvals expire after 60 seconds; Stop, denial,
cancellation, absent approval support and expiry fail closed. Terminal cleanup
clears the card. These approvals are in-memory and are not durable checkpoints.

General exposes official Browser Use indexed click/input tools only when an
approval handler exists. Every such interaction requires approval in this slice.
Input is limited to an exact quoted user-task literal, replacement of ordinary
main-document text fields, and a fresh value read after execution. Credentials,
files, dates, appending, keyboard operations and model-authored page code are
not enabled. CLI runs without an approval sink retain read-only tools.

Before approval, refresh Browser Use state and check the proposed backend node,
stable browser target/frame and current index. Bind approval to an in-memory hash
of the whole main-document HTML, live control values, URL, document time origin
and target geometry/properties.
Refuse pages above the bounded state size. Refresh and compare after approval;
a changed page or target ends the task as blocked without executing that action.
Disable upstream interaction overlays in General so our own highlights do not
invalidate the fingerprint. The pinned actor's inspection needs an explicit
upstream `DOM.getDocument` before resolving node IDs, including after input.
Browser Use still owns its transport and action mechanics. Its DOM collection
can replace a CDP attachment session while the page and backend node are unchanged;
that transient transport ID is not an element identity. The packaged approval
test reproduced this rotation. Stable target/frame/node identity plus the
document epoch and complete state hash keep the approval bound to the page.

## Tradeoffs and evidence limits

This deliberately conservative policy can block benign dynamic page changes and
requires approval for ordinary interactions. The fingerprint covers observed
DOM/control state; it cannot attest to hidden server or JavaScript state.
It establishes a conservative migration boundary, not a complete risk classifier
or a durable resume system. A future
reduction in approvals needs measured policy/targeting evidence.

URL/H1 remain caller-owned task completion criteria; input-value verification
proves a field effect, not an arbitrary business workflow. Controlled local form
integration uses the official Agent with offline HTTP model responses. It proves
browser/product/approval plumbing, not autonomous General model accuracy. No
additional paid inference or external form submission is required for validation.
Fast remains links only. Rust and Native Messaging schemas are unchanged.
