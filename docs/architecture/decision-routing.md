# System One decision routing

M5 adds a Python `DecisionProvider` contract for bounded browser decisions.
It is separate from the generative System Two provider planned for M6.

## Providers

- `LayaProvider` is the default. It loads the typed-decisions checkpoint on
  CPU and maps its `choice`, `score`, and `noul` answers into BROWSKI types.
- `JevProvider` is optional. It uses TypeSafe's Python SDK and requires the
  user's TypeSafe API key when called.
- `AdaptiveDecisionProvider` tries Laya first and uses Jev when Laya fails or
  the Laya-specific acceptance policy abstains. It does not blend outputs.

The same provider interface exposes bounded Choice, Score, and Noul judgments,
semantic verification, recovery classification, and progress checks. Choices
allow 2–16 named options; score rubrics allow 2–8 ordered levels.

## Calibration and acceptance

Each provider has independent per-decision temperatures and minimum-confidence
thresholds. Temperatures adjust answer probabilities. Thresholds determine
whether a result is accepted or requires fallback/escalation. Missing thresholds
are reported as unassessed (`accepted=None`); adaptive routing then asks Jev.
Raw and adjusted confidence are both retained with provider attribution.

Thresholds are application policy, not model guarantees. Fit them on held-out
browser-task data, record a calibration identifier, and evaluate coverage and
error rates before relying on automatic actions. Contract tests use fake model
and SDK clients; they do not establish live provider quality or calibration.

## Configuration

```python
from browser_agent.decisions import DecisionConfig, create_decision_provider

provider = create_decision_provider(DecisionConfig(provider="laya"))
```

`provider` accepts `laya` (default), `jev`, or `adaptive`. `DecisionConfig`
also accepts separate `calibration.laya` and `calibration.jev` mappings. The
Laya and Jev dependencies remain optional: install the `decisions-local` or
`decisions-cloud` extra from `python/` as needed.

Provider policies can be supplied as configuration data:

```python
config = DecisionConfig.model_validate(
    {
        "provider": "adaptive",
        "calibration": {
            "laya": {
                "calibration_id": "laya-browser-heldout-v1",
                "temperatures": {"choice": 1.2},
                "minimum_confidence": {"choice": 0.84, "noul": 0.9},
            },
            "jev": {
                "calibration_id": "jev-browser-heldout-v1",
                "temperatures": {"choice": 0.95},
                "minimum_confidence": {"choice": 0.78, "noul": 0.86},
            },
        },
    }
)
```

The values above are examples only; a deployment must fit its own values on
held-out data before enabling confidence-based automatic acceptance.

## Implementation status

Adapters, typed mappings, adaptive fallback, and fake-client contract tests
are implemented. The pretrained Laya checkpoint has not been downloaded or
evaluated as part of the M5 gate. No real Jev API call has been made. The
default thresholds are unset until BROWSKI has a held-out calibration corpus.

The adapters follow the providers' published Python APIs:
[Laya](https://github.com/NandhaKishorM/laya) and
[TypeSafe Python SDK](https://docs.typesafe.ai/sdk/python).
