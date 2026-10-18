"""BROWSKI 2.0 provider contract regressions, also run without model extras."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from browser_agent.engines.contracts import CompletionCriteria, PageEvidence
from browser_agent.engines.fast_contract import (
    Candidate,
    FastObservation,
    FastRequest,
    Operation,
    TypedQuestion,
    build_request,
    normalize_response,
)
from browser_agent.engines.fast_providers import JevFastProvider, LayaFastProvider


def request_fixture() -> FastRequest:
    observation = FastObservation(
        id="generation-1",
        url="http://127.0.0.1/library",
        title="Library",
        text="Choose a topic.",
        candidates=(
            Candidate(id="e1", operation=Operation.CLICK, label="Botany", role="link"),
            Candidate(id="e2", operation=Operation.CLICK, label="Geology", role="link"),
        ),
    )
    return build_request("Open Botany.", observation)


def response_fixture() -> dict[str, Any]:
    return {
        "model": "offline-contract-fixture",
        "answers": {
            "operation": {
                "choice": "CLICK",
                "probabilities": {"CLICK": 0.9, "DONE": 0.05, "BLOCKED": 0.05},
                "confidence": 0.7,
            },
            "click_target": {
                "choice": "e1",
                "probabilities": {"e1": 0.9, "e2": 0.1},
                "confidence": 0.6,
            },
        },
    }


@pytest.mark.parametrize("provider_name", ["laya", "jev"])
async def test_shared_semantic_request_through_both_adapters(
    provider_name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request = request_fixture()
    captured: list[dict[str, Any]] = []
    response = response_fixture()
    request.questions["progress"] = TypedQuestion(
        type="score",
        criteria={"0": "No progress", "1": "Progress"},
        instructions={"goal": request.goal},
    )
    response["answers"]["progress"] = {
        "type": "score",
        "score": 0.8,
        "probabilities": {"0": 0.2, "1": 0.8},
        "confidence": 0.5,
    }

    if provider_name == "jev":

        def transport(http_request: httpx.Request) -> httpx.Response:
            assert str(http_request.url) == "https://api.typesafe.ai/v1/systemone"
            body = json.loads(http_request.content)
            assert body["questions"]["progress"]["criteria"] == ["No progress", "Progress"]
            captured.append(body)
            return httpx.Response(200, json=response)

        provider = JevFastProvider(
            api_key="offline-fixture-only",
            allow_paid_api=True,
            transport=httpx.MockTransport(transport),
        )
    else:

        class OfflineProcess:
            def is_alive(self) -> bool:
                return False

            def join(self, timeout: float) -> None:
                pass

            def close(self) -> None:
                pass

        class OfflineConnection:
            def __init__(self) -> None:
                self.replies = iter(
                    [{"ready": True, "load_ms": 0}, {"response": response, "latency_ms": 1}]
                )

            def poll(self) -> bool:
                return True

            def recv(self) -> Any:
                return next(self.replies)

            def send(self, value: dict[str, Any] | None) -> None:
                if value is None:
                    return
                assert value["questions"]["progress"]["criteria"] == {
                    "0": "No progress",
                    "1": "Progress",
                }
                captured.append(value)

            def close(self) -> None:
                pass

        def offline_worker(*args: object) -> Any:
            return OfflineProcess(), OfflineConnection()

        monkeypatch.setattr("browser_agent.engines.fast_providers.start_worker", offline_worker)
        provider = LayaFastProvider(tmp_path)
    try:
        result = await provider.predict(request)
    finally:
        await provider.aclose()
    assert result.operation is Operation.CLICK
    assert result.candidate_id == "e1"
    assert result.provider == provider_name
    assert result.observation_id == request.observation.id
    assert result.scores == {"progress": pytest.approx(0.8)}
    assert captured[0]["state"] == request.body("ignored")["state"]


@pytest.mark.parametrize(
    "corruption", ["unknown", "nan", "boolean", "sum", "not_argmax", "missing"]
)
def test_malformed_provider_response_never_authorizes_an_action(corruption: str) -> None:
    response = response_fixture()
    answer = response["answers"]["click_target"]
    if corruption == "unknown":
        answer["choice"] = "unobserved"
    elif corruption == "nan":
        answer["probabilities"]["e1"] = float("nan")
    elif corruption == "boolean":
        answer["probabilities"]["e1"] = True
    elif corruption == "sum":
        answer["probabilities"]["e2"] = 0.9
    elif corruption == "not_argmax":
        answer["choice"] = "e2"
    else:
        del response["answers"]["click_target"]
    with pytest.raises(ValueError):
        normalize_response(
            request_fixture(), response, provider="fixture", model="none", latency_ms=0
        )


def test_unused_speculative_head_cannot_block_a_valid_operation() -> None:
    response = response_fixture()
    response["answers"]["type_text_target"] = {"invalid": "unused"}
    result = normalize_response(
        request_fixture(), response, provider="fixture", model="none", latency_ms=0
    )
    assert result.candidate_id == "e1"


def test_contract_rejects_version_and_duplicate_ids() -> None:
    request = request_fixture()
    with pytest.raises(ValidationError):
        FastRequest.model_validate({**request.model_dump(), "version": "unrecognized"})
    observation = request.observation.model_dump()
    observation["candidates"] = [observation["candidates"][0]] * 2
    with pytest.raises(ValidationError, match="unique"):
        FastObservation.model_validate(observation)


@pytest.mark.parametrize("paid,key", [(False, None), (False, "offline"), (True, None)])
def test_jev_needs_explicit_paid_permission_and_credentials(paid: bool, key: str | None) -> None:
    with pytest.raises(ValueError, match="Laya"):
        JevFastProvider(allow_paid_api=paid, api_key=key)


async def test_jev_redirect_never_forwards_credentials() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "https://unexpected.invalid"})

    provider = JevFastProvider(
        allow_paid_api=True, api_key="offline-fixture-only", transport=httpx.MockTransport(redirect)
    )
    try:
        with pytest.raises(RuntimeError, match="307"):
            await provider.predict(request_fixture())
    finally:
        await provider.aclose()


def test_done_alone_is_not_completion_evidence() -> None:
    criteria = CompletionCriteria(url="http://127.0.0.1/botany", heading="Botany")
    assert not criteria.verify(None)
    assert not criteria.verify(PageEvidence(url=criteria.url, title="Botany", headings=["Error"]))
    assert not criteria.verify(
        PageEvidence(url="http://127.0.0.1/", title="Botany", headings=["Botany"])
    )
    assert criteria.verify(PageEvidence(url=criteria.url, title="Plants", headings=["Botany"]))


def test_done_is_ineligible_until_explicit_outcome_evidence_is_satisfied() -> None:
    request = request_fixture()
    constrained = build_request(request.goal, request.observation, allow_done=False)
    assert "DONE" not in constrained.questions["operation"].criteria
    assert "BLOCKED" in constrained.questions["operation"].criteria
