# ADR-026: Fast field intent without text generation

Date: 2026-10-18 · Status: bounded text-field slice

## Problem and decision

Laya and Jev select typed operations/targets; neither supplies arbitrary input
text. The Fast loop exposed only links. Importing the entire Legacy decision
pipeline to obtain values would reintroduce competing state/execution machinery.

Extract the existing quoted set/fill/type grammar and label normalization from
Legacy `decisions/task_values.py` into the runtime-independent `task_literals.py`.
Legacy keeps its soft abstention behavior. Fast uses strict validation: bounded,
nonblank quoted field/value pairs, no conflicts, no control characters, no
instructions interpreted inside literal contents. Unsupported imperative field
syntax is blocked. Bounds remain eight assignments, 120-character labels and
256-character values, within an 8000-character task.

Fast's Browser Use DOM/AX observation matches each named ordinary text field
uniquely and reads its live DOMSnapshot input value. Only unmet, uniquely bound
fields become TYPE_TEXT candidates. Both providers receive the same existing v2
candidate/operation question format. The executor takes the value from the
user-intent table, never a model response. Jev remains optional and live-unverified.

Reuse the approved upstream input tool from ADR-025. Each text entry needs its
own approval, fresh target/page binding and actual value verification. Link
execution retains the existing path. No submit/select/date/file/keyboard/tab
operation is added to Fast. CLI without an approval sink blocks unmet input
requirements before inference; it cannot silently claim them completed.

Keep a bounded per-task set of requested fields matched by fresh observations.
A wrong live value invalidates that field; an ambiguous label cannot supply
proof. URL/H1 must match **and every requested field must have been verified**
before completion. Missing controls cannot disappear from the requirements.
Verification failure after typing counts the invoked action and remains
unverified. No eligible candidates means bounded abstention without inference.

## Compatibility and limits

Fast v2 already defines TYPE_TEXT; serialized candidate/decision shapes do not
change. No Rust or Native Messaging schema changes are needed. The task-local
field proof is not a durable checkpoint or a generic business-workflow verifier.
Task-owned browsers still close at task completion; this does not implement
long-lived sessions or manual handoff of a filled form.

The controlled two-field development task passed with real CPU Laya and again
through the actual packaged sidebar, without hosted inference. Fixture decisions
exercise stale values, masked input, duplicate labels and missing fields; these
are mechanical regression gates, not unseen autonomous model benchmarks.
General's broader click/input plumbing remains independently configurable.
