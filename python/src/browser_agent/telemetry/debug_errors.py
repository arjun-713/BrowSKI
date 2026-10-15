"""Bounded exception locations for local debug capture, without private text."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import TypedDict

_MAX_EXCEPTION_FRAMES = 12


class ExceptionFrame(TypedDict):
    file: str
    function: str
    line: int


class ExceptionDebugMetadata(TypedDict):
    error_type: str
    frames: list[ExceptionFrame]


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
    return {"error_type": type(error).__name__, "frames": list(frames)}
