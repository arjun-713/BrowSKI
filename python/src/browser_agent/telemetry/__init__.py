"""High-level telemetry and safe local runtime diagnostics."""

from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder, record_debug
from browser_agent.telemetry.debug_sanitize import sanitize_debug_payload
from browser_agent.telemetry.tracing import get_logger

__all__ = [
    "DebugLogConfig",
    "DebugRecorder",
    "get_logger",
    "record_debug",
    "sanitize_debug_payload",
]
