# ADR-030: Owned-tab candidates on the shared Fast contract

Date: 2026-10-19 · Status: accepted for bounded owned-tab navigation

## Evidence and decision

The pinned Browser Use actor opens a `_blank` link while keeping agent focus on
the original page. Its public tab summary uses four-character IDs and can briefly
contain an empty URL or a placeholder title. Actual SDK probes verified these
behaviors and a successful explicit switch using the existing event bus.

Keep one task-owned Browser Use session. `engines/owned_tabs.py` reads fresh
actor-page evidence using full SDK target IDs, and verifies focus and URL after
the SDK SwitchTabEvent. No socket, second controller, service or dependency is
introduced. Read/switch races raise a typed TabStateChanged and consume the
existing bounded recovery budget. An eight-tab cap refuses overflow rather
than truncating ownership state.

General's existing `switch` tool resolves its SDK short ID only when exactly
one owned full target matches, then uses the same verified focus helper. Missing
or ambiguous IDs execute no switch. Fast retains full IDs throughout.

Expose non-active owned HTTP tabs on the allowed host as CLICK candidates with
role `tab`. Fast v2 already has an open role field and compatible candidate IDs;
serialized schemas and saved-v1 migration do not change. Both providers receive
the same role, label and sanitized destination. Complete private destinations,
full ownership and active target identity participate in freshness/progress.
An exact already-open destination replaces a duplicate `_blank` link candidate.
DOM targets also remain bound to the active main-document target.
New popups must reach a readable HTTP document before the opener is offered
again; transient SDK URL/title metadata cannot masquerade as a fresh stable page.
Budget exhaustion after an executed operation returns partially_completed.

This choice follows an exploratory CPU-Laya probe: a new SWITCH_TAB operation
was not selected, while the existing CLICK head selected the form tab over an
unrelated link (0.933 target probability in one saved-state probe). Those are
compatibility samples, not calibrated confidence or accuracy measurements. Do
not train the model or create a vendor-specific executor to support switching.

## Validation and limits

A local workflow opens Reference in a second tab, selects that tab and follows
its Receipt link. With deterministic fixture decisions, the last committed
adapter returned blocked after three opening clicks without selecting the
source; the implementation completed in three actions
with one independently verified switch and exactly two owned tabs. The first
real CPU-Laya run completed in 18.10 s, three actions/four decisions, two
recoveries and no generative calls/provider errors. This development sample is
not an unseen reliability or latency estimate. Use existing
parameterized engine/provider/product suites and the shared HTTP fixture.
`test_engine_cross_page.py` is a fifth migration test file justified by the
distinct cross-page ownership/provenance boundary; it does not duplicate a
server or harness. Source-to-field memory belongs in this same boundary next.

No source-transfer, authentication, persistent-session or general long-workflow
claim follows from tab selection alone. Existing per-action field/submission
approvals and receipt checks remain unchanged. Task-owned tabs close together
at task cleanup. No extension assets change; version stays 0.2.3.

Final focused engine/provider/workflow gate: 150 passed, including real CPU
Laya and official General with offline inference. Full packaged extension gate:
25 passed, four spent-navigation skips. The default Python suite passed 743
tests with 114 opt-in skips; lint/strict typing passed. One initial focused run
correctly refused a wrong replacement-date value but failed an overly narrow
total-recovery assertion: pre-action freshness can also recover. The regression
now verifies one replacement read, one write/approval and counter/event agreement;
the targeted check and full focused rerun passed. No production bound changed.
Historical Rust stalls and the bounded combined-command result remain separately
tracked in the checkpoint; the current Rust workspace passed 146 tests with one ignored.
