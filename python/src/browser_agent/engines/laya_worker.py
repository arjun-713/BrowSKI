"""One bounded, warm CPU inference process; no model downloads during tasks."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import resource
import time
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any, cast

LAYA_REVISION = "645cf366a2ae35f1086e8c20eff48f909bb49206"
LAYA_CODE_SHA256 = "d084f8720ee4a738efc3cee6e0cef78ab983af8cf17939957af2c2265fdd99d1"


def validate_checkpoint(path: Path) -> None:
    if not path.is_dir() or not (path / "model.safetensors").is_file():
        raise ValueError("Prepare the pinned Laya browser checkpoint before starting a task.")
    code = path / "modeling_laya_browser.py"
    if not code.is_file() or hashlib.sha256(code.read_bytes()).hexdigest() != LAYA_CODE_SHA256:
        raise ValueError("Laya checkpoint code does not match the reviewed pinned revision.")
    revision = path / "REVISION"
    if not revision.is_file() or revision.read_text().strip() != LAYA_REVISION:
        raise ValueError("Laya checkpoint revision marker is missing or incompatible.")


def inference_worker(connection: Connection, path: str, threads: int) -> None:
    """Load once and consume bounded request dictionaries until the parent closes."""
    try:
        os.environ["HF_MODULES_CACHE"] = str(Path(path).parent / "laya-code-cache")
        import torch
        from transformers import AutoModel

        torch.set_num_threads(threads)
        torch.set_num_interop_threads(1)
        started = time.perf_counter()
        model: Any = (
            cast(Any, AutoModel)
            .from_pretrained(
                path, trust_remote_code=True, local_files_only=True, dtype=torch.float32
            )
            .to("cpu")
            .eval()
        )
        # Force tokenizer loading before readiness, not during the first timed decision.
        _ = model.tokenizer
        connection.send({"ready": True, "load_ms": (time.perf_counter() - started) * 1000})
        while True:
            body = connection.recv()
            if body is None:
                break
            try:
                started = time.perf_counter()
                with torch.inference_mode():
                    response = model.systemone(body)
                connection.send(
                    {
                        "response": response,
                        "latency_ms": (time.perf_counter() - started) * 1000,
                        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                    }
                )
            except Exception as exc:
                connection.send({"error": type(exc).__name__})
    except (EOFError, BrokenPipeError):
        return
    except Exception as exc:
        connection.send({"error": type(exc).__name__})
    finally:
        connection.close()


def start_worker(path: Path, threads: int) -> tuple[BaseProcess, Connection]:
    validate_checkpoint(path)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=inference_worker, args=(child, str(path.resolve()), threads))
    process.start()
    child.close()
    return process, parent
