# ADR-028: Separate Fast freshness from stagnation evidence

Date: 2026-10-18 · Status: implemented bounded regression fix

## Reproduction

An isolated receipt link prevented navigation and incremented an unrelated
output counter. With one recovery retry allowed, the loop made four ineffective
clicks before its five-iteration outer budget ended. Every counter update changed
the observation hash, so `after.id != before.id` incorrectly reported progress.
The otherwise identical page with a static counter stopped after two clicks.
Both remained unverified; this was wasted execution, not reproduced false success.

## Decision

Retain the full observation hash, including body text, for model-decision
freshness. Add a private structural progress signature from URL/title, candidate
identities and values, full private destinations and requested native field state.
Compare it plus fresh visible H1 after execution. Arbitrary body text changing
by itself cannot postpone the existing failed-progress retry bound. Emit a
recovery event for each such attempt so the trace agrees with final counters.

Do not relax approval fingerprints, action validation, completion criteria or
provider contracts. A structural change is only a stagnation signal; it does
not prove a click achieved its intended result. Final URL/H1 and all requested
fields must still be independently verified. General is unchanged. No new
dependency, service, serializer, tool or extension asset is needed.

## Validation and limits

The parameterized real-Chrome regression uses an offline decision fixture and
counts actual page click events. After the change both static and ticking pages
stop after at most two ineffective actions, with false verification events and
the configured recovery budget exhausted. One observed ticking run stopped
after one click because its initial missing-candidate retry had already consumed
the first recovery allowance. These are bounded mechanical regression results,
not live-model speed or task-success benchmarks.

Fresh navigation, native-field and packaged-sidebar regressions remain required.
Body text can still invalidate a pending decision or human approval; that
conservative false-block question is separate and unresolved. Structural churn,
such as repeated element replacement, can still look like change. This does not
claim generic semantic progress detection or long-horizon planning.
