# ADR-008: Luna active decisions, Laya shadow only

Date: 2026-10-06 · Status: accepted

## Context

The Laya-only evaluation did not establish reliable action execution. Its
confidence values are not trusted as calibrated evidence. The product must
continue to use BROWSKI's shared decision-provider contract where useful, but
must not let an untrusted shadow decision control the browser. Jev is not
needed for this runtime phase.

## Decision

- GPT-6 Luna is the only provider allowed to produce executable decisions.
- For bounded immediate actions, Luna receives a finite set of semantic
  candidates. Its returned action must bind to the current observation and
  match one supplied candidate exactly before it can reach the executor.
- Laya may receive a bounded comparison request after Luna has selected an
  action. Its answer, confidence, error, or unavailability cannot alter the
  action, authorize an action, or block Luna's result.
- Jev remains disabled. No Jev API calls are part of this phase.
- Completion, high-risk confirmation, and Rust deterministic verification
  remain code-enforced boundaries.

## Consequences

The runtime may incur Luna API use for bounded decisions that previously used
System One. Shadow telemetry can later inform a separately reviewed Laya
policy, but is not a benchmark or calibration result. Laya confidence must not
be compared numerically with Luna confidence. The design accepts higher model
cost to keep the current execution policy aligned with measured evidence.

## Validation

Tests must verify that an invalid Luna action fails closed, an exact bounded
Luna action is the only action returned, and a different Laya shadow answer
cannot change it. No live model request is required for those contract tests.
