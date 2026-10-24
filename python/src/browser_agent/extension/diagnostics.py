"""Authenticated, content-free checks of an idle attached browser.

This protocol shares Native Messaging framing and the owner-only bridge token.
It never claims the extension connection, changes ownership, or invokes models.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from browser_agent.session import BrowserSession


class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["runtime.diagnostics"] = "runtime.diagnostics"
    protocol_version: Literal[1] = 1
    request_id: str

    def validated_id(self) -> str:
        return str(UUID(self.request_id))


class DiagnosticCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    status: Literal["PASS", "FAIL", "WARN", "INFO"]
    detail: str


class DiagnosticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["runtime.diagnostics.result"] = "runtime.diagnostics.result"
    protocol_version: Literal[1] = 1
    request_id: str
    checks: list[DiagnosticCheck] = Field(max_length=16)


def _persistence_check(database_path: Path) -> DiagnosticCheck:
    try:
        with tempfile.TemporaryFile(dir=database_path.parent) as stream:
            stream.write(b"browski diagnostic")
            stream.flush()
    except OSError:
        return DiagnosticCheck(
            name="Persistence directory", status="FAIL", detail="database directory is not writable"
        )
    return DiagnosticCheck(
        name="Persistence directory",
        status="PASS",
        detail="temporary write succeeded; existing checkpoints were not modified",
    )


def _key_check(config_path: Path | None) -> DiagnosticCheck:
    from browser_agent.cli.config import ExecutionEngine, load_config

    config = load_config(config_path)
    if config.agent.engine is ExecutionEngine.FAST or not config.agent.allow_paid_api:
        return DiagnosticCheck(
            name="Runtime OpenAI configuration",
            status="INFO",
            detail="not required by the active local/disabled engine",
        )

    from browser_agent.credentials import configured_openai_api_key

    configured = configured_openai_api_key() is not None
    return DiagnosticCheck(
        name="Runtime OpenAI configuration",
        status="PASS" if configured else "WARN",
        detail="key present; connectivity not tested"
        if configured
        else "no key configured in runtime",
    )


def _graph_checks(browser: BrowserSession, config_path: Path | None) -> list[DiagnosticCheck]:
    from browser_agent.cli.config import ExecutionEngine, load_config

    checks: list[DiagnosticCheck] = []
    try:
        config = load_config(config_path)
        if config.agent.engine is not ExecutionEngine.LEGACY:
            return [
                DiagnosticCheck(
                    name="Agent configuration",
                    status="PASS",
                    detail=f"{config.agent.engine.value} configuration validated; "
                    "no inference performed",
                )
            ]
        from browser_agent.agent import AgentRuntime, LunaDecisionAgent

        # Construction compiles the actual graph but never schedules a node.
        # No SQLite saver, HTTP client request or shadow decision is started.
        agent = LunaDecisionAgent(
            None,
            None,
            model=config.reasoning.model,
            default_effort=config.reasoning.effort,
            site_aliases=config.site_aliases,
        )
        AgentRuntime(agent, browser)
    except Exception:
        checks.append(
            DiagnosticCheck(
                name="Agent graph",
                status="FAIL",
                detail="graph construction failed; no model request sent",
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                name="Agent graph",
                status="PASS",
                detail="compiled against attached session; no node executed",
            )
        )
    return checks


async def inspect_attached_runtime(
    *,
    request_id: str,
    browser: BrowserSession | None,
    extension_connected: bool,
    run_owns_browser: bool,
    config_path: Path | None,
    database_path: Path,
) -> DiagnosticResponse:
    """Probe the existing owned browser and return no browser content."""
    from browser_agent.telemetry.debug_errors import native_error_metadata

    checks = [DiagnosticCheck(name="Local runtime", status="PASS", detail="authenticated")]
    checks.append(
        DiagnosticCheck(
            name="Extension connection",
            status="PASS" if extension_connected else "WARN",
            detail="protocol v1 negotiated" if extension_connected else "connect the side panel",
        )
    )
    checks.append(
        DiagnosticCheck(
            name="Attached browser",
            status="PASS" if browser is not None else "WARN",
            detail="explicit tab ownership present"
            if browser is not None
            else "attach a tab first",
        )
    )
    checks.append(await asyncio.to_thread(_persistence_check, database_path))
    checks.append(await asyncio.to_thread(_key_check, config_path))
    if run_owns_browser:
        checks.append(
            DiagnosticCheck(
                name="Browser probes",
                status="INFO",
                detail="skipped while a run owns browser state",
            )
        )
    elif browser is not None:
        for name, operation in (
            ("CDP round-trip", browser.probe_connection),
            ("DOM observation", browser.observe),
        ):
            try:
                await operation()
            except Exception as exc:
                metadata = native_error_metadata(exc)
                kind = metadata.get("native_error_type", type(exc).__name__)
                checks.append(
                    DiagnosticCheck(name=name, status="FAIL", detail=f"probe failed: {kind}")
                )
                break
            else:
                checks.append(
                    DiagnosticCheck(name=name, status="PASS", detail="Rust read completed")
                )
        checks.extend(await asyncio.to_thread(_graph_checks, browser, config_path))
    return DiagnosticResponse(request_id=request_id, checks=checks)


def _read_endpoint(socket_path: Path) -> tuple[Path, str]:
    from browser_agent.extension.native_host import read_runtime_token, validate_runtime_socket

    endpoint = socket_path.expanduser()
    validate_runtime_socket(endpoint)
    return endpoint, read_runtime_token(endpoint)


async def probe_runtime(socket_path: Path) -> DiagnosticResponse:
    """Authenticate without consuming the real extension's connection slot."""
    from browser_agent.extension.wire import read_native_frame, write_native_frame

    endpoint, token = await asyncio.to_thread(_read_endpoint, socket_path)
    request = DiagnosticRequest(request_id=str(uuid4()))
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(endpoint)), timeout=3)
    try:
        await write_native_frame(writer, {"type": "runtime.auth", "token": token})
        await write_native_frame(writer, request.model_dump())
        response = DiagnosticResponse.model_validate(
            await asyncio.wait_for(read_native_frame(reader), timeout=90)
        )
        if response.request_id != request.request_id:
            raise ValueError("diagnostic response does not match request")
        return response
    finally:
        writer.close()
        await writer.wait_closed()
