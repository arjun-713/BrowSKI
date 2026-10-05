"""A real process exit must not erase a LangGraph checkpoint."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_checkpoint_resumes_after_writer_process_exits(tmp_path: Path) -> None:
    database = tmp_path / "agent-checkpoints.sqlite"
    worker = Path(__file__).parent / "helpers" / "sqlite_checkpoint_worker.py"
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root
        if existing_pythonpath is None
        else os.pathsep.join((source_root, existing_pythonpath))
    )

    subprocess.run(
        [sys.executable, str(worker), str(database), "write"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    resumed = subprocess.run(
        [sys.executable, str(worker), str(database), "resume"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert json.loads(resumed.stdout) == {"count": 42}


def test_agent_runtime_resumes_after_process_exit(tmp_path: Path) -> None:
    database = tmp_path / "agent-runtime-checkpoints.sqlite"
    worker = Path(__file__).parent / "helpers" / "sqlite_checkpoint_worker.py"
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    fixture = Path(__file__).resolve().parents[2] / "tests/fixtures/m3/form-flow.html"
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root
        if existing_pythonpath is None
        else os.pathsep.join((source_root, existing_pythonpath))
    )

    paused = subprocess.run(
        [sys.executable, str(worker), str(database), "runtime-write", str(fixture)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    resumed = subprocess.run(
        [sys.executable, str(worker), str(database), "runtime-resume", str(fixture)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert json.loads(paused.stdout) == {
        "run_id": "runtime-restart",
        "status": "running",
        "done": False,
    }
    assert json.loads(resumed.stdout) == {
        "run_id": "runtime-restart",
        "status": "completed",
        "done": True,
    }
