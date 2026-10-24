"""Read-only local environment checks for the BROWSKI CLI."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import Annotated, cast

import typer

from browser_agent.cli.config import (
    BrowskiConfig,
    ConfigError,
    ExecutionEngine,
    FastProviderName,
    load_config,
)


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


_NATIVE_HOST_NAME = "com.browski.runtime"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    detail: str


def _check_python() -> DoctorCheck:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    status = CheckStatus.PASS if sys.version_info >= (3, 12) else CheckStatus.FAIL
    detail = version if status == CheckStatus.PASS else f"{version}; Python 3.12+ is required"
    return DoctorCheck("Python", status, detail)


def _check_rust_binding() -> DoctorCheck:
    try:
        import_module("browser_agent._core")
    except Exception as exc:
        return DoctorCheck("Rust binding", CheckStatus.FAIL, type(exc).__name__)
    return DoctorCheck("Rust binding", CheckStatus.PASS, "browser_agent._core imports")


def _find_chromium() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        executable = shutil.which(name)
        if executable:
            return executable
    return None


def _check_chromium() -> DoctorCheck:
    executable = _find_chromium()
    if executable is None:
        return DoctorCheck("Chromium", CheckStatus.FAIL, "not found on PATH")
    return DoctorCheck("Chromium", CheckStatus.PASS, executable)


def _check_sqlite_temp_write() -> DoctorCheck:
    try:
        with tempfile.TemporaryDirectory(prefix="browski-doctor-") as temp_dir:
            database_path = Path(temp_dir) / "check.sqlite3"
            with sqlite3.connect(database_path) as connection:
                connection.execute("CREATE TABLE doctor_check (value INTEGER)")
                connection.execute("INSERT INTO doctor_check VALUES (1)")
    except (OSError, sqlite3.Error) as exc:
        return DoctorCheck("SQLite temp write", CheckStatus.FAIL, type(exc).__name__)
    return DoctorCheck("SQLite temp write", CheckStatus.PASS, "temporary database created")


def _check_openai_key(config: BrowskiConfig) -> DoctorCheck:
    needs_openai = (
        config.agent.engine is ExecutionEngine.GENERAL
        or config.agent.engine is ExecutionEngine.LEGACY
        and config.reasoning.enabled
    )
    if not needs_openai or not config.agent.allow_paid_api:
        return DoctorCheck("OpenAI key", CheckStatus.INFO, "not needed by configured reasoning")
    from browser_agent.credentials import configured_openai_api_key

    if configured_openai_api_key() is not None:
        return DoctorCheck("OpenAI key", CheckStatus.PASS, "present; value is not displayed")
    return DoctorCheck(
        "OpenAI key",
        CheckStatus.WARN,
        "not found in the system keyring or environment",
    )


async def _check_laya_health(config: BrowskiConfig) -> DoctorCheck:
    from ipaddress import ip_address
    from urllib.parse import urlparse

    from browser_agent.decisions.laya import LayaProvider

    endpoint = urlparse(config.decision.laya_endpoint)
    hostname = endpoint.hostname
    is_loopback = hostname == "localhost"
    if hostname:
        try:
            is_loopback = is_loopback or ip_address(hostname).is_loopback
        except ValueError:
            pass
    if endpoint.scheme != "http" or not is_loopback:
        return DoctorCheck(
            "Laya service",
            CheckStatus.WARN,
            "health probe skipped; doctor checks only local HTTP services",
        )

    health = await LayaProvider(
        endpoint_url=config.decision.laya_endpoint,
        api_key_env="BROWSKI_DOCTOR_NO_LAYA_KEY",
    ).health_check()
    if health.available:
        return DoctorCheck("Laya service", CheckStatus.PASS, "health endpoint is available")
    detail = health.detail or "health endpoint is unavailable"
    return DoctorCheck("Laya service", CheckStatus.WARN, detail)


def _default_extension_path() -> Path:
    return Path(__file__).resolve().parents[4] / "extension"


def _extension_package_path(config: BrowskiConfig) -> Path:
    return config.extension.package_path or _default_extension_path()


def _native_host_candidates(config: BrowskiConfig) -> list[Path]:
    if config.extension.native_host_manifest is not None:
        return [config.extension.native_host_manifest]

    home = Path.home()
    return [
        home / ".config/google-chrome/NativeMessagingHosts",
        home / ".config/chromium/NativeMessagingHosts",
        home / "Library/Application Support/Google/Chrome/NativeMessagingHosts",
        home / "AppData/Local/Google/Chrome/User Data/NativeMessagingHosts",
        home / ".mozilla/native-messaging-hosts",
    ]


def check_extension_package(config: BrowskiConfig) -> DoctorCheck:
    extension_path = _extension_package_path(config)
    if extension_path.is_dir():
        manifest = extension_path / ".output/chrome-mv3/manifest.json"
    else:
        manifest = extension_path
    if manifest.is_file():
        return DoctorCheck("Extension package", CheckStatus.PASS, "built MV3 manifest is present")
    return DoctorCheck(
        "Extension package", CheckStatus.INFO, "not found; extension transport is optional"
    )


def check_native_host(config: BrowskiConfig) -> DoctorCheck:
    candidates = _native_host_candidates(config)
    manifest_path = next(
        (
            candidate if candidate.is_file() else candidate / f"{_NATIVE_HOST_NAME}.json"
            for candidate in candidates
            if candidate.is_file() or (candidate / f"{_NATIVE_HOST_NAME}.json").is_file()
        ),
        None,
    )
    if manifest_path is not None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DoctorCheck("Native host", CheckStatus.WARN, "manifest is unreadable")
        if not isinstance(manifest, dict):
            return DoctorCheck("Native host", CheckStatus.WARN, "manifest is invalid")
        typed_manifest = cast(dict[str, object], manifest)
        if typed_manifest.get("name") != _NATIVE_HOST_NAME:
            return DoctorCheck(
                "Native host", CheckStatus.WARN, "manifest name is not BROWSKI's host"
            )
        host_path = typed_manifest.get("path")
        if not isinstance(host_path, str) or not Path(host_path).is_file():
            return DoctorCheck("Native host", CheckStatus.WARN, "host executable is missing")
        return DoctorCheck(
            "Native host", CheckStatus.PASS, "BROWSKI host manifest and executable exist"
        )
    return DoctorCheck("Native host", CheckStatus.INFO, "BROWSKI host manifest not found")


def check_extension_bridge(socket_path: Path | None = None) -> DoctorCheck:
    """Inspect bridge endpoint files without connecting or consuming a client slot."""
    from browser_agent.extension.service import default_socket_path

    endpoint = (socket_path or default_socket_path()).expanduser()
    token_path = endpoint.with_suffix(".token")
    try:
        socket_stat = endpoint.lstat()
        token_stat = token_path.lstat()
    except FileNotFoundError:
        return DoctorCheck(
            "Extension bridge",
            CheckStatus.WARN,
            "bridge service is not running; use `browski serve`",
        )
    except OSError as exc:
        return DoctorCheck("Extension bridge", CheckStatus.WARN, type(exc).__name__)

    current_uid = os.getuid()
    socket_is_private = (
        stat.S_ISSOCK(socket_stat.st_mode)
        and socket_stat.st_uid == current_uid
        and stat.S_IMODE(socket_stat.st_mode) & 0o077 == 0
    )
    token_is_private = (
        stat.S_ISREG(token_stat.st_mode)
        and token_stat.st_uid == current_uid
        and stat.S_IMODE(token_stat.st_mode) & 0o077 == 0
        and token_stat.st_size <= 128
    )
    if not socket_is_private or not token_is_private:
        return DoctorCheck(
            "Extension bridge",
            CheckStatus.WARN,
            "socket or authentication token has unsafe type or permissions",
        )
    return DoctorCheck(
        "Extension bridge",
        CheckStatus.INFO,
        "private endpoint files are present; doctor does not probe the live socket",
    )


def _collect_doctor_checks(config: BrowskiConfig) -> list[DoctorCheck]:
    checks = [
        _check_python(),
        _check_rust_binding(),
        _check_chromium(),
        _check_sqlite_temp_write(),
        _check_openai_key(config),
        check_extension_bridge(),
        check_extension_package(config),
        check_native_host(config),
    ]
    if config.agent.engine is not ExecutionEngine.LEGACY:
        from browser_agent.engines.laya_worker import validate_checkpoint

        if (
            config.agent.engine is ExecutionEngine.FAST
            and config.agent.fast_provider is FastProviderName.LAYA
        ):
            try:
                validate_checkpoint(Path(config.agent.laya_checkpoint).expanduser())
                checks.append(
                    DoctorCheck(
                        "Laya checkpoint",
                        CheckStatus.PASS,
                        "pinned files present; no inference performed",
                    )
                )
            except (ValueError, OSError):
                checks.append(
                    DoctorCheck(
                        "Laya checkpoint",
                        CheckStatus.WARN,
                        "not prepared; run browski prepare-laya and configure its absolute path",
                    )
                )
        provider = (
            config.agent.fast_provider.value
            if config.agent.engine is ExecutionEngine.FAST
            else config.agent.text_provider.value
        )
        paid = "permitted" if config.agent.allow_paid_api else "disabled"
        checks.append(
            DoctorCheck(
                "Runtime policy",
                CheckStatus.INFO,
                f"{config.agent.engine.value} / {provider}; paid APIs {paid}; "
                "no inference performed.",
            )
        )
        return checks
    checks.append(asyncio.run(_check_laya_health(config)))

    reasoning_status = "active" if config.reasoning.enabled else "disabled"
    jev_status = "enabled" if config.decision.jev_enabled else "disabled"
    policy_detail = (
        f"{config.reasoning.model} {reasoning_status}; decision provider "
        f"{config.decision.provider.value} ({config.decision.mode.value}); "
        f"Jev {jev_status}."
    )
    if config.decision.provider.value == "laya":
        policy_detail += " Luna selects executable actions; Laya is non-executing shadow only."

    checks.append(DoctorCheck("Runtime policy", CheckStatus.WARN, policy_detail))
    return checks


ConfigPathOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help="Optional TOML configuration file (defaults to packaged policy).",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
]


def doctor(
    config_path: ConfigPathOption = None,
    extension: Annotated[
        bool,
        typer.Option(
            "--extension",
            help="Probe idle attached browser through authenticated runtime; no model calls.",
        ),
    ] = False,
) -> None:
    """Check local BROWSKI prerequisites without running a browser task."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"FAIL Configuration: {exc}")
        raise typer.Exit(code=1) from exc

    checks = _collect_doctor_checks(config)
    if extension:
        from browser_agent.extension.diagnostics import probe_runtime
        from browser_agent.extension.native_host import NativeHostError
        from browser_agent.extension.service import default_socket_path

        try:
            response = asyncio.run(probe_runtime(default_socket_path()))
            checks.extend(
                DoctorCheck(check.name, CheckStatus(check.status), check.detail)
                for check in response.checks
            )
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, NativeHostError):
            checks.append(
                DoctorCheck(
                    "Local runtime",
                    CheckStatus.FAIL,
                    "authenticated probe unavailable; start current runtime and connect extension",
                )
            )
    for check in checks:
        typer.echo(f"{check.status.value:<4} {check.name}: {check.detail}")

    if any(check.status == CheckStatus.FAIL for check in checks):
        raise typer.Exit(code=1)
