"""Opt-in, sanitized, bounded local JSONL debug capture."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import stat
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, cast

from browser_agent.telemetry.debug_sanitize import sanitize_debug_payload

_LOGGER = logging.getLogger(__name__)
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MIN_CONFIG_BYTES = 1_024
_MAX_CONFIG_BYTES = 1024 * 1024 * 1024
_MAX_CONFIG_SESSIONS = 10_000
_MAX_CONFIG_RETENTION_DAYS = 3_650
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = (
    os.O_RDWR
    | os.O_APPEND
    | os.O_CREAT
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


@dataclass(frozen=True)
class DebugLogConfig:
    enabled: bool = False
    directory: Path = Path("debug-logs")
    max_session_bytes: int = 16 * 1024 * 1024
    max_sessions: int = 100
    retention_days: int = 30

    def __post_init__(self) -> None:
        _validate_integer(
            "max_session_bytes",
            self.max_session_bytes,
            _MIN_CONFIG_BYTES,
            _MAX_CONFIG_BYTES,
        )
        _validate_integer("max_sessions", self.max_sessions, 1, _MAX_CONFIG_SESSIONS)
        _validate_integer(
            "retention_days",
            self.retention_days,
            1,
            _MAX_CONFIG_RETENTION_DAYS,
        )


def _validate_integer(name: str, value: object, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


@dataclass
class _LogFile:
    file: BinaryIO
    run_id: str
    session_id: str
    max_bytes: int
    size: int
    sequence: int
    truncated: bool
    lock: threading.Lock = field(default_factory=threading.Lock)
    failed: bool = False
    references: int = 1


@dataclass(frozen=True)
class _Binding:
    log_file: _LogFile
    session_id: str


_CURRENT_BINDING: contextvars.ContextVar[_Binding | None] = contextvars.ContextVar(
    "browser_agent_debug_log_binding",
    default=None,
)


class DebugRecorder:
    """Own one debug-log root and bind records to an active run context."""

    def __init__(self, config: DebugLogConfig) -> None:
        self.config = config
        self._open_lock = threading.Lock()
        self._active_logs: dict[str, _LogFile] = {}

    @contextmanager
    def bind(self, run_id: str, session_id: str) -> Generator[None]:
        """Bind this context to one run; storage failures disable capture safely."""
        log_file: _LogFile | None = None
        if self.config.enabled:
            if not _valid_identifier(run_id) or not _valid_identifier(session_id):
                _warn_safely("Debug capture disabled for an invalid run or session identifier")
            else:
                try:
                    log_file = self._acquire_run(run_id, session_id)
                except Exception:
                    _warn_safely("Debug capture could not open its local log")

        # A disabled or failed nested session must not inherit another run's log.
        binding = _Binding(log_file, session_id) if log_file is not None else None
        token = _CURRENT_BINDING.set(binding)
        try:
            yield
        finally:
            _CURRENT_BINDING.reset(token)
            if log_file is not None:
                self._release_run(log_file)

    def _acquire_run(self, run_id: str, session_id: str) -> _LogFile:
        with self._open_lock:
            existing = self._active_logs.get(run_id)
            if existing is not None:
                existing.references += 1
                return existing
            if len(self._active_logs) >= self.config.max_sessions:
                raise OSError("too many active debug sessions")
            log_file = self._open_run(run_id, session_id)
            self._active_logs[run_id] = log_file
            return log_file

    def _release_run(self, log_file: _LogFile) -> None:
        with self._open_lock:
            log_file.references -= 1
            if log_file.references > 0:
                return
            self._active_logs.pop(log_file.run_id, None)
            try:
                log_file.file.close()
            except Exception:
                _warn_safely("Debug capture could not close its local log")

    def _open_run(self, run_id: str, session_id: str) -> _LogFile:
        root_fd = _open_secure_directory(self.config.directory)
        try:
            run_fd = _open_child_directory(root_fd, run_id)
            fd = -1
            try:
                fd = os.open("events.jsonl", _FILE_FLAGS, 0o600, dir_fd=run_fd)
                file_stat = os.fstat(fd)
                if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_uid != os.getuid()
                    or file_stat.st_nlink != 1
                ):
                    raise OSError("debug log is not an owned regular file")
                os.fchmod(fd, 0o600)
                os.fchmod(run_fd, 0o700)
                file = os.fdopen(fd, "r+b", buffering=0)
                fd = -1
                sequence, truncated = _read_log_state(
                    file,
                    self.config.max_session_bytes,
                )
                result = _LogFile(
                    file=file,
                    run_id=run_id,
                    session_id=session_id,
                    max_bytes=self.config.max_session_bytes,
                    size=file_stat.st_size,
                    sequence=sequence,
                    truncated=truncated or file_stat.st_size >= self.config.max_session_bytes,
                )
                _cleanup_old_sessions(
                    root_fd,
                    self.config,
                    exclude=frozenset(self._active_logs) | {run_id},
                )
                return result
            finally:
                if fd >= 0:
                    os.close(fd)
                os.close(run_fd)
        finally:
            os.close(root_fd)


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and _RUN_ID_PATTERN.fullmatch(value) is not None


def _open_secure_directory(path: Path) -> int:
    absolute = path.expanduser().absolute()
    parts = absolute.parts
    fd = os.open(parts[0], _DIRECTORY_FLAGS)
    try:
        for part in parts[1:]:
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=fd)
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
                os.fchmod(next_fd, 0o700)
            os.close(fd)
            fd = next_fd
        root_stat = os.fstat(fd)
        if root_stat.st_uid != os.getuid():
            raise OSError("debug log directory is not owned by the current user")
        os.fchmod(fd, 0o700)
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_child_directory(parent_fd: int, name: str) -> int:
    try:
        child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    child_stat = os.fstat(child_fd)
    if child_stat.st_uid != os.getuid():
        os.close(child_fd)
        raise OSError("debug session directory is not owned by the current user")
    os.fchmod(child_fd, 0o700)
    return child_fd


def _cleanup_old_sessions(
    root_fd: int,
    config: DebugLogConfig,
    *,
    exclude: frozenset[str],
) -> None:
    expiry = (datetime.now(UTC) - timedelta(days=config.retention_days)).timestamp()
    candidates: list[tuple[float, str]] = []
    try:
        entries = os.scandir(root_fd)
    except OSError:
        return
    with entries:
        for index, entry in enumerate(entries):
            if index >= config.max_sessions * 2:
                break
            if entry.name in exclude or not _valid_identifier(entry.name):
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                session_stat = entry.stat(follow_symlinks=False)
                if session_stat.st_uid != os.getuid():
                    continue
                child_fd = os.open(entry.name, _DIRECTORY_FLAGS, dir_fd=root_fd)
                try:
                    file_stat = os.stat("events.jsonl", dir_fd=child_fd, follow_symlinks=False)
                    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != os.getuid():
                        continue
                    names: list[str] = []
                    with os.scandir(child_fd) as child_entries:
                        for child_index, child_entry in enumerate(child_entries):
                            if child_index >= 2:
                                break
                            names.append(child_entry.name)
                    if names != ["events.jsonl"]:
                        continue
                    candidates.append((max(session_stat.st_mtime, file_stat.st_mtime), entry.name))
                finally:
                    os.close(child_fd)
            except OSError:
                continue

    candidates.sort()
    expired = [candidate for candidate in candidates if candidate[0] < expiry]
    excess = max(0, len(candidates) - config.max_sessions + 1)
    removable = {name for _, name in expired}
    for _, name in candidates:
        if excess <= 0:
            break
        removable.add(name)
        excess -= 1

    for _, name in candidates:
        if name not in removable:
            continue
        try:
            child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=root_fd)
            try:
                os.unlink("events.jsonl", dir_fd=child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=root_fd)
        except OSError:
            continue


def _read_log_state(file: BinaryIO, maximum: int) -> tuple[int, bool]:
    file.seek(0, os.SEEK_END)
    size = file.tell()
    if size > maximum:
        return 0, True
    tail_size = 64 * 1024
    # A public response can span more than one tail block. Expand only until
    # the last complete JSONL record is available, bounded by the session cap.
    while True:
        offset = max(0, size - tail_size)
        file.seek(offset)
        existing = file.read(tail_size)
        if offset == 0:
            break
        preceding_newline = existing[:-1].rfind(b"\n")
        if preceding_newline >= 0:
            existing = existing[preceding_newline + 1 :]
            break
        tail_size = min(size, tail_size * 2)
    sequence = 0
    truncated = False
    for line in existing.splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            fields = cast(dict[str, object], record)
            value = fields.get("sequence")
            if isinstance(value, int) and not isinstance(value, bool):
                sequence = max(sequence, value)
            if fields.get("event") == "debug_log_truncated":
                truncated = True
    return sequence, truncated


def record_debug(
    event: str,
    payload: Mapping[str, object],
    step: int | None = None,
) -> None:
    """Write a sanitized event to the current context's bounded JSONL file."""
    binding = _CURRENT_BINDING.get()
    if binding is None:
        return
    log_file = binding.log_file
    if log_file.failed:
        return
    try:
        safe_event = _sanitize_event_name(event)
        safe_payload = sanitize_debug_payload(payload)
        if step is not None and (isinstance(step, bool) or step < 0):
            step = None
        with log_file.lock:
            if log_file.failed or log_file.truncated:
                return
            envelope: dict[str, object] = {
                "schema_version": 1,
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "sequence": log_file.sequence + 1,
                "run_id": log_file.run_id,
                "session_id": binding.session_id,
                "event": safe_event,
                "step": step,
                "payload": safe_payload,
            }
            encoded = _encode_record(envelope)
            marker_size = len(_encode_truncation_record(log_file, binding.session_id))
            if log_file.size + len(encoded) + marker_size > log_file.max_bytes:
                _write_truncation_marker(log_file, binding.session_id)
                return
            _write_all(log_file.file, encoded)
            log_file.sequence += 1
            log_file.size += len(encoded)
    except Exception:
        log_file.failed = True
        _warn_safely("Debug capture stopped after a local logging failure")


def _sanitize_event_name(event: str) -> str:
    if not event:
        return "invalid_event"
    safe = event[:128]
    if has_sensitive_event_name(safe):
        return "redacted_event"
    return safe


def has_sensitive_event_name(value: str) -> bool:
    return sanitize_debug_payload({"event": value}).get("event") == "[REDACTED]"


def _encode_record(record: Mapping[str, object]) -> bytes:
    return (
        json.dumps(record, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def _write_all(file: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = file.write(view)
        if written <= 0:
            raise OSError("debug log write made no progress")
        view = view[written:]


def _write_truncation_marker(log_file: _LogFile, session_id: str) -> None:
    if log_file.truncated:
        return
    encoded = _encode_truncation_record(log_file, session_id)
    if log_file.size + len(encoded) <= log_file.max_bytes:
        _write_all(log_file.file, encoded)
        log_file.sequence += 1
        log_file.size += len(encoded)
    log_file.truncated = True


def _encode_truncation_record(log_file: _LogFile, session_id: str) -> bytes:
    marker = {
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "sequence": log_file.sequence + 1,
        "run_id": log_file.run_id,
        "session_id": session_id,
        "event": "debug_log_truncated",
        "step": None,
        "payload": {"reason": "session_size_limit"},
    }
    return _encode_record(marker)


def _warn_safely(message: str) -> None:
    try:
        _LOGGER.warning(message)
    except Exception:
        pass
