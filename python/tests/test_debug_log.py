from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from browser_agent.telemetry.debug_log import (
    DebugLogConfig,
    DebugRecorder,
    record_debug,
)


def _read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _enabled_config(
    directory: Path,
    *,
    max_session_bytes: int = 16 * 1024 * 1024,
    max_sessions: int = 100,
    retention_days: int = 30,
) -> DebugLogConfig:
    return DebugLogConfig(
        enabled=True,
        directory=directory,
        max_session_bytes=max_session_bytes,
        max_sessions=max_sessions,
        retention_days=retention_days,
    )


def test_disabled_recorder_does_not_create_files(tmp_path: Path) -> None:
    recorder = DebugRecorder(DebugLogConfig(directory=tmp_path / "debug-logs"))

    with recorder.bind("run-1", "session-1"):
        record_debug("step", {"message": "ordinary diagnostic"})

    assert not (tmp_path / "debug-logs").exists()


def test_records_are_sequenced_and_resume_appends(tmp_path: Path) -> None:
    recorder = DebugRecorder(_enabled_config(tmp_path / "debug-logs"))

    with recorder.bind("run-1", "session-1"):
        record_debug("started", {"message": "first"})
        record_debug("step", {"message": "second"}, step=2)

    with recorder.bind("run-1", "session-2"):
        record_debug("resumed", {"message": "third"})

    events = _read_events(tmp_path / "debug-logs" / "run-1" / "events.jsonl")
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert [event["session_id"] for event in events] == [
        "session-1",
        "session-1",
        "session-2",
    ]
    assert events[1]["step"] == 2


def test_disabled_nested_session_does_not_inherit_another_run_log(tmp_path: Path) -> None:
    root = tmp_path / "debug-logs"
    enabled = DebugRecorder(_enabled_config(root))
    disabled = DebugRecorder(DebugLogConfig(directory=root))
    with enabled.bind("outer-run", "session-1"):
        record_debug("outer-before", {})
        with disabled.bind("private-run", "session-2"):
            record_debug("must_not_be_captured", {})
        record_debug("outer-after", {})
    events = _read_events(root / "outer-run" / "events.jsonl")
    assert [event["event"] for event in events] == ["outer-before", "outer-after"]
    assert not (root / "private-run").exists()


def test_resume_sequence_survives_a_large_last_record(tmp_path: Path) -> None:
    root = tmp_path / "debug-logs"
    recorder = DebugRecorder(_enabled_config(root))
    with recorder.bind("large-run", "session-1"):
        record_debug("large_response", {"items": ["diagnostic text " * 100] * 100})
    with recorder.bind("large-run", "session-2"):
        record_debug("resumed", {})

    events = _read_events(root / "large-run" / "events.jsonl")
    assert [event["sequence"] for event in events] == [1, 2]


def test_nested_and_concurrent_bindings_share_run_sequence(tmp_path: Path) -> None:
    recorder = DebugRecorder(_enabled_config(tmp_path / "debug-logs"))

    with recorder.bind("nested-run", "outer-session"):
        record_debug("outer-before", {})
        with recorder.bind("nested-run", "inner-session"):
            record_debug("inner", {})
        record_debug("outer-after", {})

    worker_count = 4
    writes_per_worker = 5
    barrier = Barrier(worker_count)

    def write_worker(worker_id: int) -> None:
        with recorder.bind("concurrent-run", f"session-{worker_id}"):
            barrier.wait(timeout=5)
            for event_number in range(writes_per_worker):
                record_debug(
                    "concurrent-step",
                    {"worker": worker_id, "event_number": event_number},
                )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(write_worker, worker_id) for worker_id in range(worker_count)]
        for future in futures:
            future.result(timeout=10)

    nested_events = _read_events(tmp_path / "debug-logs" / "nested-run" / "events.jsonl")
    assert [event["session_id"] for event in nested_events] == [
        "outer-session",
        "inner-session",
        "outer-session",
    ]

    concurrent_events = _read_events(tmp_path / "debug-logs" / "concurrent-run" / "events.jsonl")
    assert len(concurrent_events) == worker_count * writes_per_worker
    assert [event["sequence"] for event in concurrent_events] == list(
        range(1, worker_count * writes_per_worker + 1)
    )
    assert {event["session_id"] for event in concurrent_events} == {
        f"session-{worker_id}" for worker_id in range(worker_count)
    }


def test_log_directories_and_file_are_owner_only(tmp_path: Path) -> None:
    root = tmp_path / "private-debug"
    recorder = DebugRecorder(_enabled_config(root))

    with recorder.bind("permission-run", "session-1"):
        record_debug("event", {})

    run_directory = root / "permission-run"
    log_file = run_directory / "events.jsonl"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(run_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(log_file.stat().st_mode) == 0o600


def test_sensitive_values_are_removed_from_jsonl(tmp_path: Path) -> None:
    recorder = DebugRecorder(_enabled_config(tmp_path / "debug-logs"))
    payload = {
        "password": "human-password-123",
        "form": {
            "role": "textbox",
            "label": "Account password",
            "value": "field-password-456",
        },
        "prompt": "Use password='prompt-password-789' to continue",
        "secret_text": "Credential sk-test-1234567890abcdef was displayed",
        "contact": "Contact alex@example.test or call 202-555-0136",
        "url": "https://example.test/path?token=query-secret#fragment-secret",
        "reasoning": "hidden model reasoning",
        "screenshot": "do-not-store-this-image",
        "target_ref": "@submit-button",
    }

    with recorder.bind("privacy-run", "session-1"):
        record_debug("model_input", payload)

    log_text = (tmp_path / "debug-logs" / "privacy-run" / "events.jsonl").read_text()
    for secret in (
        "human-password-123",
        "field-password-456",
        "prompt-password-789",
        "sk-test-1234567890abcdef",
        "alex@example.test",
        "202-555-0136",
        "query-secret",
        "fragment-secret",
        "hidden model reasoning",
        "do-not-store-this-image",
    ):
        assert secret not in log_text
    assert "https://example.test/path" in log_text
    assert "@submit-button" in log_text


def test_size_limit_writes_truncation_marker_within_bound(tmp_path: Path) -> None:
    maximum = 1_024
    recorder = DebugRecorder(_enabled_config(tmp_path / "debug-logs", max_session_bytes=maximum))

    with recorder.bind("bounded-run", "session-1"):
        record_debug("oversized", {"text": "ordinary text " * 300})
        record_debug("after-limit", {"text": "later"})

    path = tmp_path / "debug-logs" / "bounded-run" / "events.jsonl"
    events = _read_events(path)
    assert path.stat().st_size <= maximum
    assert events[-1]["event"] == "debug_log_truncated"
    assert len(events) == 1


def test_invalid_run_id_and_symlink_directory_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "debug-logs"
    recorder = DebugRecorder(_enabled_config(root))

    with recorder.bind("../outside", "session-1"):
        record_debug("invalid", {})
    assert not (tmp_path / "outside" / "events.jsonl").exists()

    target = tmp_path / "target"
    target.mkdir()
    root.mkdir()
    (root / "linked-run").symlink_to(target, target_is_directory=True)
    with recorder.bind("linked-run", "session-2"):
        record_debug("symlink", {})

    assert not (target / "events.jsonl").exists()


def test_retention_removes_oldest_owned_run_directories(tmp_path: Path) -> None:
    root = tmp_path / "debug-logs"
    root.mkdir(mode=0o700)
    now = 1_800_000_000
    for run_id, age_seconds in (("older-run", 120), ("newer-run", 60)):
        run_directory = root / run_id
        run_directory.mkdir(mode=0o700)
        log_file = run_directory / "events.jsonl"
        log_file.write_text("{}\n")
        log_file.chmod(0o600)
        timestamp = now - age_seconds
        os.utime(log_file, (timestamp, timestamp))
        os.utime(run_directory, (timestamp, timestamp))

    recorder = DebugRecorder(_enabled_config(root, max_sessions=2, retention_days=30))
    with recorder.bind("current-run", "session-1"):
        record_debug("new", {})

    assert not (root / "older-run").exists()
    assert (root / "newer-run" / "events.jsonl").is_file()
    assert (root / "current-run" / "events.jsonl").is_file()
