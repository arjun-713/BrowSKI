"""Bounded exception locations for local debug capture, without private text."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import TypedDict

_MAX_EXCEPTION_FRAMES = 12
_NATIVE_CATEGORIES = {
    "component": {"browser_core"},
    "operation": {"observe", "probe_connection"},
    "failure_kind": {"FRAME", "TAB", "TIMEOUT", "EXECUTION", "NAVIGATION", "SAFETY", "UNKNOWN"},
    "native_error_type": {
        "FRAME_DETACHED",
        "TARGET_CLOSED",
        "COMMAND_TIMEOUT",
        "PROTOCOL_ERROR",
        "NAVIGATION_FAILED",
        "NO_ACTIVE_TAB",
        "INVALID_RESPONSE",
        "CONNECTION_LOST",
        "SESSION_CLOSED",
        "BRIDGE_JSON_DEPTH_LIMIT",
        "BRIDGE_MESSAGE_TOO_LARGE",
        "EXTENSION_COMMAND_REJECTED",
        "EXTENSION_SESSION_MISMATCH",
        "EXTENSION_COMMAND_TIMEOUT",
        "EXTENSION_BRIDGE_FAILURE",
        "OBSERVATION_TIMEOUT",
        "BROWSER_RUNTIME_FAILURE",
    },
}
_CDP_METHODS = {
    "Accessibility.getFullAXTree",
    "DOM.describeNode",
    "DOM.getBoxModel",
    "DOM.getDocument",
    "DOM.resolveNode",
    "DOMSnapshot.captureSnapshot",
    "Page.getLayoutMetrics",
    "Runtime.callFunctionOn",
    "Runtime.evaluate",
}


class ExceptionFrame(TypedDict):
    file: str
    function: str
    line: int


class ExceptionDebugMetadata(TypedDict):
    error_type: str
    frames: list[ExceptionFrame]
    native: dict[str, str | bool | int]


def native_error_metadata(error: BaseException) -> dict[str, str | bool | int]:
    """Copy reviewed native categories, never arbitrary exception messages."""
    values: dict[str, str | bool | int] = {}
    for key, allowed in _NATIVE_CATEGORIES.items():
        value = getattr(error, key, None)
        if isinstance(value, str) and value in allowed:
            values[key] = value
    recoverable = getattr(error, "recoverable", None)
    if isinstance(recoverable, bool):
        values["recoverable"] = recoverable
    code = getattr(error, "cdp_code", None)
    if type(code) is int:
        values["cdp_code"] = code
    method = getattr(error, "cdp_method", None)
    if isinstance(method, str) and method in _CDP_METHODS:
        values["cdp_method"] = method
    return values


def exception_debug_metadata(error: BaseException) -> ExceptionDebugMetadata:
    """Keep code locations; never inspect exception arguments or frame locals.

    Browser and provider exceptions can echo credentials or page content.
    Locations make first-observation failures diagnosable without persisting
    those arbitrary messages, source lines or local variable values.
    """
    frames: deque[ExceptionFrame] = deque(maxlen=_MAX_EXCEPTION_FRAMES)
    traceback = error.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        frames.append(
            {
                "file": Path(code.co_filename).name,
                "function": code.co_name,
                "line": traceback.tb_lineno,
            }
        )
        traceback = traceback.tb_next
    return {
        "error_type": type(error).__name__,
        "frames": list(frames),
        "native": native_error_metadata(error),
    }
