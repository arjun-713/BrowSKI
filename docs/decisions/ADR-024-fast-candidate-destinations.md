# ADR-024: Versioned link destinations and navigation guards

Date: 2026-10-18 · Status: accepted for implementation

A real Chrome regression reproduced an href-only mutation after decision time:
the anchor kept its backend node ID and visible label, the old fingerprint stayed
valid, and Fast clicked the new destination. Final verification refused success,
but the wrong action had already happened. Stabilizing the initial snapshot was
necessary to isolate this defect from an unrelated initial snapshot change.

Fast now includes the complete resolved destination in its private freshness
fingerprint. Both decision providers also receive an optional `Candidate.href`
with a bounded URL containing scheme, authority and path; query/fragment data is
excluded from model-facing destination metadata. Credentials and malformed URLs
are excluded from navigation candidates. This supplies missing destination context for repeated
link labels while preserving provider-independent execution.

The serialized Fast request/decision contract becomes `browski.fast.v2`. An
optional field would still be rejected by old strict v1 Candidate readers, so
we version the changed shape explicitly. New readers upgrade known v1 saved
requests to v2, defaulting omitted hrefs to empty; unknown versions fail. New
writers emit v2. Existing Browser Use, Native Messaging v1 and Rust/PyO3 browser
schemas are unchanged. No model training or provider-specific action loop is added.

General retains official Browser Use mechanics behind a small tool-policy
override. Model-proposed navigation is restricted to bounded HTTP(S) URLs without
embedded credentials before upstream execution. Its navigation/read tool
allowlist continues to exclude form submits, arbitrary evaluation and file tools.

Validate href invalidation in real Chrome, malformed/credential URL rejection,
legacy capture migration, equivalent provider inputs and packaged regression
execution. The four first-look navigation tasks were frozen and run against
`0ebefdb` before these changes; further runs of those tasks are regressions,
not new unseen evaluations. Broader forms/tabs/approval migration remains open.
