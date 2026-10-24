# ADR-027: Native date and dropdown execution with independent field proof

Date: 2026-10-18 · Status: bounded Fast slice

## Evidence and decision

The pinned Browser Use SDK can return without error after an invalid date is
normalized to an empty value or an out-of-range date leaves native validity
false. Its dropdown label-or-value matching can select Red when that option's
value is Blue. These behaviors were reproduced on isolated loopback pages;
successful tool return is insufficient evidence of the requested outcome.

Keep the official Browser Use executor. Add `engines/native_fields.py` for fixed,
bounded main-document control inspection through its existing actor/session.
No second browser transport or provider-specific executor is introduced.
Fast opts into native dates via TYPE_TEXT and single-select via SELECT, both
already present in Fast v2. Values still come only from the shared user-literal
parser; Laya/Jev choose operations and targets using the same contract.

Before approval, validate an exact calendar date in YYYY-MM-DD form and native
constraints using an event-free detached clone. Read actual properties after
execution, requiring the requested value and native validity. Resolve dropdowns
by one visible option label first, otherwise one value, rejecting disabled or
ambiguous matches. Use an SDK token only when its label-or-value matching
uniquely identifies that option. Postconditions also require that exact option
to be selected; duplicate values alone do not prove selection. Bound option
counts and serialized state; reject unsupported or oversized projections.

Reuse per-action approval and fresh page/target binding from ADR-025. If a write
replaces its control, allow one fresh semantic reread with the same URL/document
epoch, target, frame, tag, unique label and native kind. Never repeat the write
to verify it. A wrong replacement value remains unverified. Count this read
recovery separately from failed-progress retries. Missing candidates receive at
most the configured three settle/reobserve retries, with no provider inference.

Recompute all requested field proof from every fresh observation. A regression
removed a verified date after the later dropdown action: old code falsely
completed; rebuilding the proof set returns partially_completed. This is a
confirmed defect and regression, not a hypothetical dynamic-page risk.

## Scope and validation

Real Chrome and CPU Laya completed a two-control development task; the same
task passed through the packaged default-Fast sidebar with two approvals and
no Legacy attachment or hosted credential lookup. Existing parameterized suites
cover invalid/ranged dates, disabled/multiple/ambiguous selects, duplicate values,
visible label attributes, SDK token collisions, delayed options, stale
constraints, replacement controls and disappearing fields. A replacement-date
case changed from blocked after one write to verified completion with two total
actions and one read recovery. Wrong replacement values still block. These are
development/regression cases, not an unseen autonomous benchmark.

General's approved ordinary text tools share live validity and reread primitives,
but General does not expose date or selection tools. No schema, dependency,
Rust, Native Messaging or extension asset change is required. Keep version 0.2.3.
Browsers still close at task end; this slice does not retain a form for manual
continuation, submit it, support custom widgets or provide durable sessions.
Full-page approval/freshness fingerprints remain conservative and may reject
unrelated page changes; investigate with reproduction before relaxing them.
