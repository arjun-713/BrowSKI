# System One decision routing

**Runtime policy (2026-10-06):** GPT-6 Luna is the only active provider that
may select an executable action. Laya is shadow-only and cannot change Luna's
choice. Jev is disabled and is not required. The lower-level provider
interfaces remain available for isolated contract work, but the product CLI
does not enable Laya or Jev as action routers.

M5 adds a Python `DecisionProvider` contract for bounded browser decisions.
M6 adds a separate structured `ReasoningProvider` for GPT-6 Luna.

## Providers

- `LayaProvider` calls a separately managed local Laya service, configured by
  endpoint and timeout. It is currently permitted only for non-executing shadow
  comparison. BROWSKI does not download model weights or start the service as
  a side effect of a decision call.
- `JevProvider` and `AdaptiveDecisionProvider` remain low-level contract
  implementations. They are disabled in the current product runtime; do not
  call Jev during this productization phase.

The same provider interface exposes bounded Choice, Score, and Noul judgments,
semantic verification, recovery classification, and progress checks. Choices
allow 2–16 named options; score rubrics allow 2–8 ordered levels.

## Calibration and acceptance

Each provider has independent per-decision temperatures and minimum-confidence
thresholds. Temperatures adjust answer probabilities. Thresholds determine
whether a result is accepted or requires fallback/escalation. Missing thresholds
are reported as unassessed (`accepted=None`). The disabled low-level adaptive
contract can request Jev fallback; the product runtime does not use that route.
Raw and adjusted confidence are both retained with provider attribution.

Thresholds are application policy, not model guarantees. Laya has not earned
action execution based on the current benchmark evaluation. Do not infer its
confidence values are comparable to Luna or to Jev. Contract tests use fake
model and SDK clients; they do not establish live provider quality or
calibration.

## Configuration

# Low-level provider factory example; this does not configure the product CLI.
```python
from browser_agent.decisions import DecisionConfig, create_decision_provider

provider = create_decision_provider(DecisionConfig(provider="laya"))
```

The low-level `DecisionConfig` contract accepts `laya`, `jev`, or `adaptive`.
This is not the current product CLI policy. It also accepts separate
`calibration.laya` and `calibration.jev` mappings, plus `laya_endpoint`,
`laya_timeout_ms`, `laya_health_timeout_ms`, `jev_timeout_ms`, and
`fallback_to_jev`. Install the `decisions-cloud` extra to use the optional Jev
adapter in isolated contract work. Laya runs as a separately installed
service. For a CPU-only local setup, use a separate environment and the upstream
server settings:

```sh
python3 -m venv .venv-laya
.venv-laya/bin/python -m pip install "laya[serve]"
LAYA_HOST=127.0.0.1 LAYA_DEVICE=cpu LAYA_MODELS=english \
  LAYA_PRELOAD=1 LAYA_THREADS=4 .venv-laya/bin/laya-serve
```

The service listens on `127.0.0.1:8001`, matching BROWSKI's default Laya
endpoint. The first service start downloads the selected checkpoint if it is
not already cached. `LAYA_DEVICE`, `LAYA_MODELS`, `LAYA_PRELOAD`, and
`LAYA_THREADS` are upstream Laya service settings; they are not BROWSKI
configuration. BROWSKI does not install Laya, download weights, or start the
service. Set a different client URL through `DecisionConfig(laya_endpoint=...)`.
See the upstream [Laya HTTP server configuration](https://github.com/NandhaKishorM/laya/blob/main/docs/http-api.md).
`BROWSKI_LIVE_LAYA` and `BROWSKI_LAYA_ENDPOINT` are used only by the opt-in live
contract test, not by the regular task CLI. The adapter contract tests use a
fake transport; live CPU inference has not been run or verified in this
checkout.

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

Adapters, typed mappings, bounded candidate selection, health checks, timeout
and error mapping, fallback telemetry, and fake-client contract tests are
implemented. The M5 gate used provider fixtures. The currently installed local
CPU checkpoint is available for bounded shadow comparisons; its confidence
warning remains unresolved. No Jev call is required. Execution thresholds
remain disabled under the current shadow-only policy.

## GPT-6 Luna reasoning

`LunaDecisionAgent` sends bounded semantic actions to Luna for the active
choice. A returned action must semantically match the meaningful fields of an available candidate and bind
to a current interactable semantic reference. Only after Luna selects an
action may Laya receive an optional shadow-comparison request; the comparison
cannot change or authorize the action. Selectors and backend-node IDs are not
part of the response contract.

`OpenAILunaProvider` uses the Responses API structured-output path. The model
defaults to `gpt-6-luna` and can be configured by the caller. The OpenAI SDK is
an optional `reasoning-openai` extra, and credentials are read only when the
provider is called. Requests have a character bound, output-token bound, and
deadline. Errors are translated without returning prompts or provider payloads.

`ComplexityGate` is deterministic. It routes ordinary escalation and the
normal recovery rung to low effort. High effort is available only after the
recovery ladder evaluates a failed normal replan or another explicit complex
signal; successful progress resets the per-streak counters. xhigh is not
available in this baseline. Adapter tests use an injected fake Responses
client; live OpenAI behavior remains opt-in and unmeasured unless the live test
is run explicitly.

The [live repair report](../development/live-agent-repair-2026-10-12.md) records
the current controlled live tests. Local task checks, ephemeral verified action
batches, and owned destination proof follow
[ADR-018](../decisions/ADR-018-locally-verified-luna-actions.md). Flat ordered
milestones do not count as simultaneous subgoals for the ComplexityGate. Laya
comparisons are bounded background work and cannot block or alter Luna actions.

The adapters follow the providers' published Python APIs:
[Laya](https://github.com/NandhaKishorM/laya) and
[TypeSafe Python SDK](https://docs.typesafe.ai/sdk/python).
