"""Safe local run metadata and checkpoint retention behavior."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from browser_agent.persistence.run_metadata import SQLiteRunMetadataStore
from browser_agent.persistence.run_metrics import RunMetrics


@pytest.mark.asyncio
async def test_run_records_store_status_and_counts_without_task_content(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = SQLiteRunMetadataStore(database)

    await store.record_started("run-safe")
    await store.record_state(
        "run-safe",
        status="completed",
        steps=3,
        reasoning_calls=2,
    )

    records = await store.list_runs()

    assert len(records) == 1
    assert records[0].run_id == "run-safe"
    assert records[0].status == "completed"
    assert records[0].steps == 3
    assert records[0].reasoning_calls == 2
    assert records[0].metrics == RunMetrics()
    with sqlite3.connect(database) as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(browski_runs)").fetchall()
        }
    assert "task" not in columns
    assert "payload" not in columns


@pytest.mark.asyncio
async def test_run_clean_previews_then_deletes_only_aged_run_checkpoints(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    async with AsyncSqliteSaver.from_conn_string(str(database)) as checkpointer:
        await checkpointer.setup()

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id)
            VALUES ('old-run', '', 'old-checkpoint'), ('new-run', '', 'new-checkpoint')
            """
        )
        connection.execute(
            """
            INSERT INTO writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel)
            VALUES
                ('old-run', '', 'old-checkpoint', 'task-old', 0, 'channel'),
                ('new-run', '', 'new-checkpoint', 'task-new', 0, 'channel')
            """
        )

    store = SQLiteRunMetadataStore(database)
    await store.record_started("old-run")
    await store.record_started("new-run")
    await store.record_state(
        "old-run",
        status="completed",
        steps=2,
        reasoning_calls=1,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE browski_runs SET updated_at = ? WHERE run_id = 'old-run'",
            ("2020-01-01T00:00:00+00:00",),
        )

    cutoff = datetime(2021, 1, 1, tzinfo=UTC)
    preview = await store.clean_before(cutoff)

    assert [record.run_id for record in preview] == ["old-run"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 2

    removed = await store.clean_before(cutoff, apply=True)

    assert [record.run_id for record in removed] == ["old-run"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT thread_id FROM checkpoints").fetchall() == [("new-run",)]
        assert connection.execute("SELECT thread_id FROM writes").fetchall() == [("new-run",)]
        assert connection.execute("SELECT run_id FROM browski_runs").fetchall() == [("new-run",)]


@pytest.mark.asyncio
async def test_run_clean_skips_running_records_unless_explicitly_selected(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runs.sqlite3"
    store = SQLiteRunMetadataStore(database)
    await store.record_started("possibly-live-run")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE browski_runs SET updated_at = ? WHERE run_id = ?",
            ("2020-01-01T00:00:00+00:00", "possibly-live-run"),
        )

    cutoff = datetime(2021, 1, 1, tzinfo=UTC)
    assert await store.clean_before(cutoff) == []
    included = await store.clean_before(cutoff, include_running=True)
    assert [record.run_id for record in included] == ["possibly-live-run"]


@pytest.mark.asyncio
async def test_metrics_are_additive_and_readable_from_legacy_run_schema(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE browski_runs (
                run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                status TEXT NOT NULL, steps INTEGER NOT NULL DEFAULT 0,
                reasoning_calls INTEGER NOT NULL DEFAULT 0
            )"""
        )
        connection.execute(
            "INSERT INTO browski_runs VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "paused", 2, 1),
        )

    store = SQLiteRunMetadataStore(database)
    records = await store.list_runs()
    assert records[0].metrics == RunMetrics()
    assert await store.load_metrics("legacy") == RunMetrics()
    with sqlite3.connect(database) as connection:
        assert "browski_run_metrics" not in {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


@pytest.mark.asyncio
async def test_metrics_persist_and_cleanup_with_the_run(tmp_path: Path) -> None:
    database = tmp_path / "metrics.sqlite3"
    store = SQLiteRunMetadataStore(database)
    await store.record_started("metric-run")
    metrics = RunMetrics(
        action_count=4,
        verification_failures=1,
        recoveries=1,
        browser_code_calls=1,
        vision_calls=2,
        luna_calls=5,
        luna_none_effort_calls=1,
        luna_low_effort_calls=3,
        luna_high_effort_calls=1,
        laya_shadow_decisions=2,
    )
    await store.record_metrics(
        "metric-run",
        metrics,
        event_at="2026-01-01T00:00:01+00:00",
    )
    await store.record_state(
        "metric-run",
        status="completed",
        steps=4,
        reasoning_calls=5,
    )

    persisted = (await store.list_runs())[0].metrics
    assert persisted.action_count == 4
    assert persisted.verification_failures == 1
    assert persisted.recoveries == 1
    assert persisted.browser_code_calls == 1
    assert persisted.vision_calls == 2
    assert persisted.luna_calls == 5
    assert persisted.luna_low_effort_calls == 3
    assert persisted.luna_high_effort_calls == 1
    assert persisted.luna_none_effort_calls == 1
    assert persisted.laya_shadow_decisions == 2
    assert persisted.task_duration_ms >= 0
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE browski_runs SET updated_at=? WHERE run_id='metric-run'",
            ("2020-01-01T00:00:00+00:00",),
        )

    removed = await store.clean_before(datetime(2021, 1, 1, tzinfo=UTC), apply=True)
    assert [record.run_id for record in removed] == ["metric-run"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM browski_run_metrics").fetchone()[0] == 0


def test_run_clean_requires_timezone_aware_cutoff(tmp_path: Path) -> None:
    store = SQLiteRunMetadataStore(tmp_path / "runs.sqlite3")

    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(store.clean_before(datetime(2024, 1, 1)))
