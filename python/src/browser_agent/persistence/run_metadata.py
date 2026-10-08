"""Minimal run metadata and age-based cleanup for local checkpoint databases."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from browser_agent.persistence.run_metrics import RunMetrics

RunStatus = Literal[
    "running",
    "paused",
    "awaiting_user",
    "pending_confirmation",
    "completed",
    "failed",
    "stopped",
]


class RunMetadataError(RuntimeError):
    """Raised when the configured run database cannot be safely inspected."""


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    started_at: str
    updated_at: str
    status: str
    steps: int
    reasoning_calls: int
    metrics: RunMetrics = RunMetrics()


class SQLiteRunMetadataStore:
    """Persist only run identifiers, timestamps, status, and aggregate counts."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser()

    async def record_started(self, run_id: str) -> None:
        await asyncio.to_thread(self._record_started, run_id)

    async def record_state(
        self,
        run_id: str,
        *,
        status: RunStatus,
        steps: int,
        reasoning_calls: int,
    ) -> None:
        await asyncio.to_thread(
            self._record_state,
            run_id,
            status,
            steps,
            reasoning_calls,
        )

    async def list_runs(self, *, limit: int = 100) -> list[RunRecord]:
        if not 1 <= limit <= 1_000:
            raise ValueError("run list limit must be between 1 and 1000")
        return await asyncio.to_thread(self._list_runs, limit)

    async def record_metrics(
        self,
        run_id: str,
        metrics: RunMetrics,
        *,
        event_at: str,
    ) -> None:
        await asyncio.to_thread(self._record_metrics, run_id, metrics, event_at)

    async def load_metrics(self, run_id: str) -> RunMetrics:
        return await asyncio.to_thread(self._load_metrics, run_id)

    async def clean_before(
        self,
        cutoff: datetime,
        *,
        apply: bool = False,
        include_running: bool = False,
    ) -> list[RunRecord]:
        if cutoff.tzinfo is None:
            raise ValueError("run retention cutoff must be timezone-aware")
        normalized_cutoff = cutoff.astimezone(UTC).isoformat()
        return await asyncio.to_thread(
            self._clean_before,
            normalized_cutoff,
            apply,
            include_running,
        )

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS browski_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                steps INTEGER NOT NULL DEFAULT 0 CHECK (steps >= 0),
                reasoning_calls INTEGER NOT NULL DEFAULT 0 CHECK (reasoning_calls >= 0)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS browski_run_metrics (
                run_id TEXT PRIMARY KEY,
                task_duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (task_duration_ms >= 0),
                action_count INTEGER NOT NULL DEFAULT 0 CHECK (action_count >= 0),
                verification_failures INTEGER NOT NULL DEFAULT 0 CHECK (verification_failures >= 0),
                recoveries INTEGER NOT NULL DEFAULT 0 CHECK (recoveries >= 0),
                browser_code_calls INTEGER NOT NULL DEFAULT 0 CHECK (browser_code_calls >= 0),
                vision_calls INTEGER NOT NULL DEFAULT 0 CHECK (vision_calls >= 0),
                luna_calls INTEGER NOT NULL DEFAULT 0 CHECK (luna_calls >= 0),
                luna_none_effort_calls INTEGER NOT NULL DEFAULT 0
                    CHECK (luna_none_effort_calls >= 0),
                luna_low_effort_calls INTEGER NOT NULL DEFAULT 0 CHECK (luna_low_effort_calls >= 0),
                luna_high_effort_calls INTEGER NOT NULL DEFAULT 0
                    CHECK (luna_high_effort_calls >= 0),
                laya_shadow_decisions INTEGER NOT NULL DEFAULT 0 CHECK (laya_shadow_decisions >= 0)
            )
            """
        )

    def _record_started(self, run_id: str) -> None:
        now = _utc_now()
        try:
            with self._connect() as connection:
                self._ensure_schema(connection)
                connection.execute(
                    """
                    INSERT INTO browski_runs
                        (run_id, started_at, updated_at, status, steps, reasoning_calls)
                    VALUES (?, ?, ?, 'running', 0, 0)
                    """,
                    (run_id, now, now),
                )
        except sqlite3.Error as exc:
            raise RunMetadataError("could not record BROWSKI run metadata") from exc

    def _record_state(
        self,
        run_id: str,
        status: RunStatus,
        steps: int,
        reasoning_calls: int,
    ) -> None:
        if steps < 0 or reasoning_calls < 0:
            raise ValueError("run counters cannot be negative")
        now = _utc_now()
        try:
            with self._connect() as connection:
                self._ensure_schema(connection)
                connection.execute(
                    """
                    INSERT INTO browski_runs
                        (run_id, started_at, updated_at, status, steps, reasoning_calls)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        status = excluded.status,
                        steps = excluded.steps,
                        reasoning_calls = excluded.reasoning_calls
                    """,
                    (run_id, now, now, status, steps, reasoning_calls),
                )
        except sqlite3.Error as exc:
            raise RunMetadataError("could not update BROWSKI run metadata") from exc

    def _list_runs(self, limit: int) -> list[RunRecord]:
        if not self.database.is_file():
            return []
        try:
            with self._connect() as connection:
                if not _table_exists(connection, "browski_runs"):
                    return []
                if _table_exists(connection, "browski_run_metrics"):
                    rows = connection.execute(
                        """
                        SELECT r.run_id, r.started_at, r.updated_at, r.status, r.steps,
                            r.reasoning_calls, m.*
                        FROM browski_runs AS r
                        LEFT JOIN browski_run_metrics AS m ON m.run_id = r.run_id
                        ORDER BY r.updated_at DESC, r.run_id
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT run_id, started_at, updated_at, status, steps, reasoning_calls
                        FROM browski_runs ORDER BY updated_at DESC, run_id LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
            return [_record_from_row(row) for row in rows]
        except sqlite3.Error as exc:
            raise RunMetadataError("could not read BROWSKI run metadata") from exc

    def _record_metrics(self, run_id: str, metrics: RunMetrics, event_at: str) -> None:
        try:
            occurred = datetime.fromisoformat(event_at)
            if occurred.tzinfo is None:
                raise ValueError("event time must be timezone-aware")
            event_time = occurred.astimezone(UTC).isoformat()
            with self._connect() as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    "SELECT started_at FROM browski_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row is None:
                    return
                started = datetime.fromisoformat(str(row[0])).astimezone(UTC)
                duration_ms = max(
                    0,
                    min(
                        2**31 - 1, int((occurred.astimezone(UTC) - started).total_seconds() * 1000)
                    ),
                )
                values = metrics.to_dict()
                values["task_duration_ms"] = duration_ms
                columns = tuple(values)
                connection.execute(
                    f"""INSERT INTO browski_run_metrics (run_id, {", ".join(columns)})
                    VALUES ({", ".join("?" for _ in range(len(columns) + 1))})
                    ON CONFLICT(run_id) DO UPDATE SET
                    {", ".join(f"{column}=excluded.{column}" for column in columns)}""",
                    (run_id, *(values[column] for column in columns)),
                )
                connection.execute(
                    "UPDATE browski_runs SET updated_at = ? WHERE run_id = ?",
                    (event_time, run_id),
                )
        except (sqlite3.Error, ValueError, OverflowError) as exc:
            raise RunMetadataError("could not update BROWSKI run metrics") from exc

    def _load_metrics(self, run_id: str) -> RunMetrics:
        if not self.database.is_file():
            return RunMetrics()
        try:
            with self._connect() as connection:
                if not _table_exists(connection, "browski_run_metrics"):
                    return RunMetrics()
                row = connection.execute(
                    "SELECT * FROM browski_run_metrics WHERE run_id = ?", (run_id,)
                ).fetchone()
            return _metrics_from_row(row) if row is not None else RunMetrics()
        except sqlite3.Error as exc:
            raise RunMetadataError("could not read BROWSKI run metrics") from exc

    def _clean_before(self, cutoff: str, apply: bool, include_running: bool) -> list[RunRecord]:
        if not self.database.is_file():
            return []
        try:
            with self._connect() as connection:
                if not _table_exists(connection, "browski_runs"):
                    return []
                query = """
                    SELECT run_id, started_at, updated_at, status, steps, reasoning_calls
                    FROM browski_runs
                    WHERE updated_at < ?
                """
                if not include_running:
                    query += " AND status != 'running'"
                rows = connection.execute(
                    query + " ORDER BY updated_at, run_id", (cutoff,)
                ).fetchall()
                stale_runs = [_record_from_row(row) for row in rows]
                if apply and stale_runs:
                    self._delete_stale_runs(connection, stale_runs)
            return stale_runs
        except (sqlite3.Error, ValueError) as exc:
            raise RunMetadataError("could not safely clean old BROWSKI runs") from exc

    def _delete_stale_runs(
        self,
        connection: sqlite3.Connection,
        stale_runs: list[RunRecord],
    ) -> None:
        run_ids = [record.run_id for record in stale_runs]
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table in ("writes", "checkpoints"):
                if not _table_exists(connection, table):
                    continue
                columns = _table_columns(connection, table)
                if "thread_id" not in columns:
                    raise RunMetadataError(f"refusing to clean unexpected SQLite table {table!r}")
                _delete_thread_rows(connection, table, run_ids)
            _delete_thread_rows(connection, "browski_runs", run_ids, key="run_id")
            if _table_exists(connection, "browski_run_metrics"):
                _delete_thread_rows(connection, "browski_run_metrics", run_ids, key="run_id")
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _delete_thread_rows(
    connection: sqlite3.Connection,
    table: str,
    run_ids: list[str],
    *,
    key: str = "thread_id",
) -> None:
    if table not in {"writes", "checkpoints", "browski_runs", "browski_run_metrics"}:
        raise RunMetadataError(f"refusing to clean unexpected SQLite table {table!r}")
    for start in range(0, len(run_ids), 500):
        batch = run_ids[start : start + 500]
        placeholders = ", ".join("?" for _ in batch)
        connection.execute(
            f"DELETE FROM {table} WHERE {key} IN ({placeholders})",
            batch,
        )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in {"writes", "checkpoints"}:
        raise RunMetadataError(f"refusing to inspect unexpected SQLite table {table!r}")
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _record_from_row(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=str(row["run_id"]),
        started_at=str(row["started_at"]),
        updated_at=str(row["updated_at"]),
        status=str(row["status"]),
        steps=int(row["steps"]),
        reasoning_calls=int(row["reasoning_calls"]),
        metrics=_metrics_from_row(row),
    )


def _metrics_from_row(row: sqlite3.Row) -> RunMetrics:
    names = RunMetrics.__dataclass_fields__
    return RunMetrics.from_dict({name: row[name] for name in names if name in row.keys()})


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
