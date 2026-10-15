"""Exception diagnostics retain code locations without exception text or locals."""

from __future__ import annotations

import json

import pytest

from browser_agent.telemetry.debug_errors import exception_debug_metadata


class PrivateError(RuntimeError):
    def __str__(self) -> str:
        raise AssertionError("Debug metadata must not stringify exceptions")


def _raise_private_error() -> None:
    private_value = "private-form-value-fixture"
    raise PrivateError(private_value)


def _recursive_failure(depth: int) -> None:
    if depth:
        _recursive_failure(depth - 1)
    else:
        _raise_private_error()


def test_exception_metadata_contains_locations_without_private_values() -> None:
    with pytest.raises(PrivateError) as captured:
        _raise_private_error()
    payload = exception_debug_metadata(captured.value)

    assert payload["error_type"] == "PrivateError"
    frames = payload["frames"]
    assert frames[-1]["file"] == "test_debug_errors.py"
    assert frames[-1]["function"] == "_raise_private_error"
    assert frames[-1]["line"] > 0
    encoded = json.dumps(payload)
    assert "private-form-value-fixture" not in encoded
    assert '"locals"' not in encoded
    assert "source" not in encoded


def test_exception_metadata_keeps_only_the_last_twelve_frames() -> None:
    with pytest.raises(PrivateError) as captured:
        _recursive_failure(30)
    payload = exception_debug_metadata(captured.value)

    frames = payload["frames"]
    assert len(frames) == 12
    assert frames[-1]["function"] == "_raise_private_error"
