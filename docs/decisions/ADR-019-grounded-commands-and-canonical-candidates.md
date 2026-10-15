# ADR-019: Grounded commands and canonical candidate selection

**Status:** Active for command binding and canonical IDs; Laya execution remains
experimental and disabled by default.

**Date:** 2026-10-12

## Context

The frozen mixed-task baseline exposed missing candidates for ordinary user
phrasing and action rejection when Luna reconstructed a permitted action with
different text casing or scroll parameters. A short task also incurred a
separate planning call even when all its operations were explicitly requested
and uniquely grounded in the current observation.

The local Laya probe answered 20 scoped command cases correctly, but selected
an executable action in all four unsupported broad-choice cases. Those results
do not justify general execution routing or a production confidence threshold.

## Decision

- Bind literal user values and uniquely named options locally. Ambiguous,
  contradictory, missing, or unobserved bindings fail closed.
- For complete short commands, create a local plan with deterministic evidence
  and ask Luna directly for its next action. General tasks still use planning.
- Prefer canonical candidate IDs in Luna output. IDs resolve only to the
  current finite action set. Existing action matching, batching, Rust execution,
  risk classification, and verification remain authoritative.
  At the wire boundary, one ID form is authoritative over redundant legacy
  action fields. Mixed singular/batch ID forms and unknown IDs are rejected;
  an invalid ID never falls back to a model-supplied action. Domain contracts
  still require exactly one action representation.
- Derive native option ownership from Rust document order and frame provenance.
  Repeated labels in different selects become distinguishable. Unproven custom
  widget ownership remains ambiguous.
- Support explicitly requested cross-page recording through source-bound
  semantic evidence. The model identifies a visible source reference; local
  code reads its heading and named definition values. Model-generated values
  and legacy untrusted facts cannot authorize field writes.
- Retain bounded source/ref/generation/fingerprint proofs for requested links
  only after one new owned tab is observed. Exclude proved links from later
  candidates and apply the owned-tab limit to this link-opening path too.
  A fresh pre-action snapshot invalidates the preceding post-action cache;
  each executed action receives a fresh post-action observation.
- Permit one explicitly counted response-format repair within the remaining
  run budget. Do not retry authentication, request, timeout or context-size
  errors through that path. Invalid plans never supply fabricated evidence.
- Add a Python reasoning `task_complete` proposal with the exact initialized
  required milestone identifiers and evidence. It cannot replace proof or
  discard previously completed steps. Correcting an unusable earlier plan
  requires an explicit `milestone_plan` response. Every completion path still
  checks verified action effects, task-bound field values, required open links,
  requested destinations, terminal text and explicit confirmation requirements.
  A rejected proposal preserves the plan and continues within the existing
  call and stagnation bounds. It does not authorize another browser action.
- Consume an action-event witness when it advances a milestone, so one click
  of a shared control cannot prove two separate item operations. State checks
  remain reusable. A revised plan preserves completed identifiers only when
  their evidence is unchanged; a revision does not resurrect consumed events.
- Distinguish a requested unchanged no-submit/draft status from proof of a new
  action. That exception requires a current native status and outstanding
  task-authorized field work; static positive labels remain insufficient.
- Honor recognized explicit approval requests for each affected mutation,
  including neutral button labels. Approval for an earlier action does not
  authorize the next action. This conservative fallback may request consent
  earlier than the user's intended final step.
- Keep the experimental Laya route separate from general routing. It can
  consider only a locally established next user command and escalation. No
  experimental confidence threshold establishes universal calibration, and
  the runtime default stays Luna with optional Laya shadow comparison.

## Consequences

Short tasks can avoid a planning call, and bounded action batches can amortize
one Luna call across several independently verified actions. Canonical IDs
remove needless reconstruction of private values and action parameters.

Natural-language binding remains a bounded grammar. New web applications,
generative form creation, custom controls, and long research workflows still
require separate reliability evidence. Passing local fixtures does not prove
success on arbitrary websites.

Cross-page values describe the source snapshot captured immediately before
returning to the destination. They are not continuously refreshed observations
of background tabs; a source that changes after capture can make them outdated.

See [ADR-018](ADR-018-locally-verified-luna-actions.md), the
[task-mix corpus](../../benchmarks/task_mix/README.md), and the
[Laya probe](../../benchmarks/task_mix/laya_probe_report_20261012_v2.md).
