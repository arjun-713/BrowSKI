# ADR-029: Approved Fast form transition and receipt verification

Date: 2026-10-18 · Status: implemented bounded workflow

## Evidence and decision

The controlled Name/City form reproduced a missing workflow: Fast filled both
fields, then exhausted candidate recovery and returned partially_completed.
The executor offered no submission control. Keeping field proof only on the
current page also prevents legitimate completion once a verified form becomes
a receipt. Retaining proof across every disappearance would reintroduce the
false success fixed in ADR-027.

Recognize one explicit quoted `click "Label"` or `press "Label"` from the user
task. Reuse the existing quote scanner and bounds in `task_literals.py`; quoted
field contents cannot create actions. Reject multiple named clicks, explicit
repeat modifiers and malformed quoted labels. Ordinary navigation remains
available. This is typed intent, not a new generative planner.

Only after all requested fields are freshly verified may the unique matching
native button, submit input or link become a CLICK candidate. Laya/Jev receive
the same existing Fast v2 questions and candidate shape. Actual native action
state, including form destination/method/target and submitter overrides, joins
the private freshness hash. Destinations follow Fast's same-host HTTP policy.
The existing Browser Use click tool and per-action approval execute it; no
second executor, controller or task graph is added. Native disabled fieldsets
also invalidate the approval target.

After an approved invocation, retain only the verified field-stage checkpoint
and enter outcome waiting. Never repeat that named click, even for a no-op or
wrong receipt. Bounded fresh observations, without provider inference, must
satisfy caller-owned URL/H1 checks. Missing criteria or criteria already true
before the pending action cannot prove a transition and block before input.
Denial or page/target mutation performs no click. Click return status is not
receipt verification; traces report the actual outcome check.
Execution also binds the decision to its original observation, candidate and
operation, independently of adapter normalization. A deliberately inconsistent
fixture reproduced a link being clicked for a TYPE_TEXT decision during the
refactor; the dispatch guard now refuses it without an action. An abstaining
decision cannot authorize execution, even if it includes a candidate hint.

Receipt testing also confirmed that whole-URL `rstrip('/')` accepted a different
query or fragment value. Preserve those values exactly. Only plain query-free,
fragment-free URLs retain the prior trailing-path-slash tolerance. No serialized
schema/version change is needed; this is a stricter verification bug fix.

## Validation and limits

Real CPU Laya completed two fields and the approved Save in three decisions,
three actions, 14.42 s, with 656/709/774 ms decision times and zero hosted or
generative calls. The actual packaged sidebar passed with three distinct
approvals, no Legacy attachment and no hosted credential lookup. These are
development timings and integration evidence, not unseen performance results.

Existing parameterized suites cover fixture/live Laya, GET and actual local
POST/303/GET receipts, denial, changed values/action during approval, duplicate
buttons, no-op clicks, wrong receipts, missing/preexisting criteria and values
changed by the submit handler. Page click counters assert one invocation.
Both adapters have equivalent button-candidate contract cases. Legacy value
parsing regressions remain required; its behavior is preserved.

This does not verify arbitrary server business state, authenticate sessions,
retain task browsers, synthesize values or support arbitrary button sequences.
Callers must supply discriminating receipt criteria; the controlled task's URL
includes both actual submitted values. Richer receipt predicates remain open.
GET/POST testing uses isolated loopback pages only. General's configured scope
and budgets are unchanged. No new dependencies, extension assets, Native
Messaging schemas or Rust code are introduced; extension version stays 0.2.3.
