# ADR-004: Local-first typed System One decision providers

- Status: Accepted for provider contracts; execution routing superseded by
  [ADR-008](ADR-008-luna-active-decision-policy.md)
- Date: 2026-10-02

## Context

The context and routing decision below record the original M5 policy. Current
product execution uses Luna, Laya shadow only and no Jev calls under ADR-008.
The shared provider interface and independent calibration contracts remain valid.

BROWSKI needs fast, bounded classifications for browser state while keeping
browser execution deterministic. The M4 agent loop had only an injected fake
decision agent. The architecture plan selects Laya as the local default and
TypeSafe Jev as an optional cloud fallback/comparison. Their confidence values
must not be treated as interchangeable.

## Decision

- Define a Python `DecisionProvider` contract shared by Laya and Jev.
- Support finite Choice decisions, ordinal Score judgments, and binary Noul
  probabilities, plus semantic verification, recovery classification, and
  progress checks built on those primitives.
- Default to local CPU Laya. Keep Jev optional behind the same interface.
- Provide an adaptive wrapper that tries Laya first and calls Jev after a
  provider error or Laya-specific abstention. Do not combine or compare raw
  confidence across providers.
- Keep provider-specific probability calibration and acceptance thresholds.
  Leave thresholds unset until fit and evaluated on held-out BROWSKI tasks.
- Keep adapters, SDKs, configuration, and calibration in Python. Rust remains
  independent of model/provider APIs.

## Consequences

The Laya model service is a separate local process; BROWSKI does not load model
weights during browser decisions. The TypeSafe SDK is an optional extra.
Fake-backed tests can validate contracts without model downloads, credentials,
or network access.
Those tests do not establish live performance, model accuracy, or calibrated
thresholds. Those claims require a held-out benchmark in a later evaluation
pass.

GPT-6 Luna remains the only planned generative reasoning model and is outside
this decision-provider contract; no Luna, Sol, or Astra route is added here.

## References

- [System One decision routing](../architecture/decision-routing.md)
- Architecture authority: `ARCHITECTURE_PLAN.md` in the separate
  Agent-Browser-Benchmark checkout.
- [Laya project](https://github.com/NandhaKishorM/laya)
- [TypeSafe Python SDK](https://docs.typesafe.ai/sdk/python)
