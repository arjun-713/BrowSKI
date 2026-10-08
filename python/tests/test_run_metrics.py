"""Content-free aggregate behavior for locally persisted run metrics."""

from browser_agent.agent.events import RuntimeEvent, RuntimeEventType
from browser_agent.persistence.run_metrics import RunMetricKind, RunMetrics, RunMetricsAggregator


def _event(event_type: RuntimeEventType, *, status: str = "completed") -> RuntimeEvent:
    return RuntimeEvent.create(
        session_id="session",
        run_id="safe-run",
        sequence=1,
        step=1,
        event_type=event_type,
        status=status,
    )


def test_aggregator_counts_only_known_content_free_runtime_events() -> None:
    metrics = RunMetricsAggregator()
    metrics.observe_event(_event(RuntimeEventType.ACTION_COMPLETED))
    metrics.observe_event(_event(RuntimeEventType.VERIFICATION_COMPLETED, status="failed"))
    metrics.observe_event(_event(RuntimeEventType.RECOVERY_STARTED, status="running"))
    metrics.observe_event(_event(RuntimeEventType.BROWSER_CODE_STARTED, status="running"))
    metrics.observe_event(_event(RuntimeEventType.VERIFICATION_COMPLETED))

    result = metrics.get("safe-run")
    assert result.action_count == 1
    assert result.verification_failures == 1
    assert result.recoveries == 1
    assert result.browser_code_calls == 1


def test_provider_metrics_restore_and_increment_without_values() -> None:
    metrics = RunMetricsAggregator()
    initial = RunMetrics(luna_calls=1, luna_low_effort_calls=1)
    metrics.restore("safe-run", initial)
    metrics.increment("safe-run", RunMetricKind.LUNA_HIGH_EFFORT_CALL)
    metrics.increment("safe-run", RunMetricKind.VISION_CALL)
    metrics.increment("safe-run", RunMetricKind.LAYA_SHADOW_DECISION)

    result = metrics.get("safe-run")
    assert result.luna_calls == 2
    assert result.luna_low_effort_calls == 1
    assert result.luna_high_effort_calls == 1
    assert result.vision_calls == 1
    assert result.laya_shadow_decisions == 1
    assert set(result.to_dict()) == set(RunMetrics.__dataclass_fields__)
    assert not any("secret" in key for key in result.to_dict())
