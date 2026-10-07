"""Runtime-side validation for the versioned extension control protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeGuard, cast
from urllib.parse import urlsplit

PROTOCOL_VERSION = 1
DEBUGGER_PROTOCOL_VERSION = 1
MAX_EVENT_ID_LENGTH = 128
MAX_DEBUGGER_CAPABILITIES = 128
MAX_TASK_LENGTH = 4_000


class ExtensionProtocolError(ValueError):
    """Raised when an extension message is malformed or replayed."""


def _is_record(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _has_only_keys(value: Mapping[str, object], keys: set[str]) -> bool:
    return set(value).issubset(keys)


def _text(
    value: object,
    *,
    maximum: int = 512,
    minimum: int = 1,
) -> TypeGuard[str]:
    return isinstance(value, str) and minimum <= len(value) <= maximum


def _string_list(value: object) -> bool:
    if not _is_list(value) or len(value) > MAX_DEBUGGER_CAPABILITIES:
        return False
    strings: list[str] = []
    for item in value:
        if not _text(item, maximum=128):
            return False
        strings.append(item)
    return len(strings) == len(set(strings))


def _valid_origin(value: object) -> bool:
    if not _text(value, maximum=2_048):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
    )


def _valid_payload(message_type: str, payload: object) -> bool:
    if not _is_record(payload):
        return False
    fields = payload

    match message_type:
        case "extension.hello":
            versions = fields.get("protocolVersions")
            return (
                _has_only_keys(
                    fields,
                    {
                        "protocolVersions",
                        "debuggerProtocolVersion",
                        "debuggerMethods",
                        "debuggerEvents",
                    },
                )
                and _is_list(versions)
                and PROTOCOL_VERSION in versions
                and all(_is_int(version) and version > 0 for version in versions)
                and _is_int(fields.get("debuggerProtocolVersion"))
                and fields["debuggerProtocolVersion"] == DEBUGGER_PROTOCOL_VERSION
                and _string_list(fields.get("debuggerMethods"))
                and _string_list(fields.get("debuggerEvents"))
            )
        case "runtime.snapshot.request":
            sequence = fields.get("afterSequence")
            return (
                _has_only_keys(fields, {"afterSequence"})
                and type(sequence) is int
                and sequence >= 0
            )
        case "runtime.task.submit":
            task = fields.get("task")
            return (
                _has_only_keys(fields, {"sessionId", "task"})
                and _text(fields.get("sessionId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(task, maximum=MAX_TASK_LENGTH)
                and task.strip() == task
            )
        case "runtime.approval.respond":
            decision = fields.get("decision")
            return (
                _has_only_keys(fields, {"sessionId", "approvalId", "decision"})
                and _text(fields.get("sessionId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(fields.get("approvalId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(decision, maximum=16)
                and decision in {"approve", "deny"}
            )
        case "runtime.task.control":
            return (
                _has_only_keys(fields, {"sessionId", "runId", "control"})
                and _text(fields.get("sessionId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(fields.get("runId"), maximum=MAX_EVENT_ID_LENGTH)
                and fields.get("control") in {"pause", "resume", "stop"}
            )
        case "runtime.credentials.set":
            return (
                _has_only_keys(fields, {"apiKey"})
                and _text(fields.get("apiKey"), maximum=4_096)
                and "\n" not in cast(str, fields["apiKey"])
                and "\r" not in cast(str, fields["apiKey"])
            )
        case "runtime.credentials.clear" | "runtime.credentials.status.request":
            return _has_only_keys(fields, set())
        case "browser.tab.attached":
            tab_id = fields.get("tabId")
            return (
                _has_only_keys(fields, {"attachmentId", "tabId", "origin", "sessionId"})
                and _text(fields.get("attachmentId"), maximum=MAX_EVENT_ID_LENGTH)
                and _is_int(tab_id)
                and tab_id >= 0
                and _valid_origin(fields.get("origin"))
                and _text(fields.get("sessionId"), maximum=MAX_EVENT_ID_LENGTH)
            )
        case "browser.tab.detached":
            return (
                _has_only_keys(fields, {"attachmentId", "reason"})
                and _text(fields.get("attachmentId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(fields.get("reason"), maximum=1_000)
            )
        case "debugger.command.result":
            common = {"attachmentId", "commandId", "sessionId"}
            has_result = _has_only_keys(fields, common | {"result"})
            has_error = _has_only_keys(fields, common | {"error"})
            return (
                _text(fields.get("attachmentId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(fields.get("commandId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(fields.get("sessionId"), maximum=MAX_EVENT_ID_LENGTH)
                and (
                    (has_result and _is_record(fields.get("result")))
                    or (has_error and _text(fields.get("error"), maximum=1_000))
                )
            )
        case "debugger.event":
            sequence = fields.get("sequence")
            return (
                _has_only_keys(
                    fields, {"attachmentId", "sessionId", "sequence", "method", "params"}
                )
                and _text(fields.get("attachmentId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(fields.get("sessionId"), maximum=MAX_EVENT_ID_LENGTH)
                and type(sequence) is int
                and sequence > 0
                and _text(fields.get("method"), maximum=128)
                and _is_record(fields.get("params"))
            )
        case "browser.event.dropped":
            return (
                _has_only_keys(fields, {"attachmentId", "method", "reason"})
                and _text(fields.get("attachmentId"), maximum=MAX_EVENT_ID_LENGTH)
                and _text(fields.get("method"), maximum=128)
                and _text(fields.get("reason"), maximum=128)
            )
        case _:
            return False


class ExtensionMessageValidator:
    """Validate protocol envelopes and reject duplicate IDs per connection."""

    def __init__(self, *, max_messages: int = 4_096) -> None:
        if max_messages <= 0:
            raise ValueError("message replay window must be greater than zero")
        self._max_messages = max_messages
        self._seen_ids: set[str] = set()
        self._hello_seen = False

    def validate(self, value: object) -> dict[str, object]:
        if not _is_record(value):
            raise ExtensionProtocolError("extension message must be an object")
        message = value
        if not _has_only_keys(message, {"protocolVersion", "type", "eventId", "payload"}):
            raise ExtensionProtocolError("extension message has unexpected envelope fields")
        if (
            type(message.get("protocolVersion")) is not int
            or message["protocolVersion"] != PROTOCOL_VERSION
        ):
            raise ExtensionProtocolError("extension protocol version is unsupported")
        message_type = message.get("type")
        event_id = message.get("eventId")
        if not _text(message_type, maximum=128) or not _text(event_id, maximum=MAX_EVENT_ID_LENGTH):
            raise ExtensionProtocolError("extension message type or event ID is invalid")
        if event_id in self._seen_ids:
            raise ExtensionProtocolError("extension message event ID was already used")
        if len(self._seen_ids) >= self._max_messages:
            raise ExtensionProtocolError("extension message replay window is exhausted")
        if not _valid_payload(message_type, message.get("payload")):
            raise ExtensionProtocolError("extension message payload is invalid")
        if not self._hello_seen and message_type != "extension.hello":
            raise ExtensionProtocolError("extension hello must be the first message")
        if self._hello_seen and message_type == "extension.hello":
            raise ExtensionProtocolError("extension hello may only be sent once per connection")

        self._seen_ids.add(event_id)
        self._hello_seen = self._hello_seen or message_type == "extension.hello"
        return message
