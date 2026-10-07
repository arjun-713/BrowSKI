"""Runtime-side extension protocol validation tests."""

from __future__ import annotations

import pytest

from browser_agent.extension.protocol import (
    ExtensionMessageValidator,
    ExtensionProtocolError,
)


def _message(
    event_id: str,
    message_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "protocolVersion": 1,
        "type": message_type,
        "eventId": event_id,
        "payload": payload,
    }


def _hello(event_id: str = "hello-1") -> dict[str, object]:
    return _message(
        event_id,
        "extension.hello",
        {
            "protocolVersions": [1],
            "debuggerProtocolVersion": 1,
            "debuggerMethods": ["DOM.getDocument"],
            "debuggerEvents": ["Page.loadEventFired"],
        },
    )


def test_validator_accepts_hello_then_bounded_task_submission() -> None:
    validator = ExtensionMessageValidator()
    hello = _hello()
    task = _message(
        "task-1",
        "runtime.task.submit",
        {"sessionId": "session-1", "task": "Open the first result"},
    )

    assert validator.validate(hello) == hello
    assert validator.validate(task) == task


def test_validator_accepts_scoped_task_control() -> None:
    validator = ExtensionMessageValidator()
    validator.validate(_hello())
    message = _message(
        "control-1",
        "runtime.task.control",
        {"sessionId": "session-1", "runId": "run-1", "control": "pause"},
    )

    assert validator.validate(message) == message


def test_validator_accepts_bounded_credential_management_messages() -> None:
    validator = ExtensionMessageValidator()
    validator.validate(_hello())
    configure = _message(
        "credential-1",
        "runtime.credentials.set",
        {"apiKey": "test-key-value"},
    )
    clear = _message("credential-2", "runtime.credentials.clear", {})
    status = _message("credential-3", "runtime.credentials.status.request", {})

    assert validator.validate(configure) == configure
    assert validator.validate(clear) == clear
    assert validator.validate(status) == status


def test_validator_requires_hello_before_other_messages() -> None:
    validator = ExtensionMessageValidator()
    task = _message(
        "task-1",
        "runtime.task.submit",
        {"sessionId": "session-1", "task": "Open the first result"},
    )

    with pytest.raises(ExtensionProtocolError, match="hello must be the first"):
        validator.validate(task)


def test_validator_rejects_replayed_event_id_and_duplicate_hello() -> None:
    validator = ExtensionMessageValidator()
    validator.validate(_hello())

    with pytest.raises(ExtensionProtocolError, match="already used"):
        validator.validate(_hello())
    with pytest.raises(ExtensionProtocolError, match="only be sent once"):
        validator.validate(_hello("hello-2"))


@pytest.mark.parametrize(
    "message",
    [
        {**_hello(), "protocolVersion": 2},
        {**_hello(), "extra": True},
        _message("bad-type", "runtime.unknown", {}),
        _message("bad-task", "runtime.task.submit", {"task": "x" * 4_001}),
        _message(
            "bad-origin",
            "browser.tab.attached",
            {
                "attachmentId": "attachment-1",
                "tabId": 3,
                "origin": "file:///etc/passwd",
                "sessionId": "session-1",
            },
        ),
        _message(
            "bad-approval",
            "runtime.approval.respond",
            {"sessionId": "s", "approvalId": "a", "decision": []},
        ),
        _message(
            "bad-control",
            "runtime.task.control",
            {"sessionId": "s", "runId": "r", "control": "execute"},
        ),
        _message(
            "bad-credential",
            "runtime.credentials.set",
            {"apiKey": "x" * 4_097},
        ),
    ],
)
def test_validator_rejects_unsupported_or_malformed_messages(
    message: dict[str, object],
) -> None:
    validator = ExtensionMessageValidator()

    with pytest.raises(ExtensionProtocolError):
        validator.validate(message)


def test_validator_exhausts_bounded_replay_window() -> None:
    validator = ExtensionMessageValidator(max_messages=1)
    validator.validate(_hello())

    with pytest.raises(ExtensionProtocolError, match="window is exhausted"):
        validator.validate(_message("snapshot-1", "runtime.snapshot.request", {"afterSequence": 0}))
