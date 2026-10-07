"""Typed TOML configuration for the local BROWSKI CLI."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import cast


class ConfigError(ValueError):
    """Raised when a BROWSKI configuration file is invalid."""


class PrivacyMode(StrEnum):
    STANDARD = "standard"
    PRIVACY_FIRST = "privacy_first"
    OFFLINE = "offline"


class ExtensionTransportMode(StrEnum):
    DISABLED = "disabled"
    NATIVE_HOST = "native_host"


class TraceLevel(StrEnum):
    OFF = "off"
    STANDARD = "standard"
    DETAILED = "detailed"


class DecisionMode(StrEnum):
    ACTIVE = "active"
    SHADOW = "shadow"
    DISABLED = "disabled"


class DecisionProviderName(StrEnum):
    LAYA = "laya"
    JEV = "jev"
    ADAPTIVE = "adaptive"


@dataclass(frozen=True, slots=True)
class AgentConfig:
    orchestrator: str


@dataclass(frozen=True, slots=True)
class ReasoningConfig:
    provider: str
    model: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class DecisionConfig:
    provider: DecisionProviderName
    mode: DecisionMode
    jev_enabled: bool
    laya_endpoint: str
    shadow_telemetry: bool


@dataclass(frozen=True, slots=True)
class PrivacyConfig:
    mode: PrivacyMode


@dataclass(frozen=True, slots=True)
class SafetyConfig:
    confirm_high_risk_actions: bool


@dataclass(frozen=True, slots=True)
class ExtensionConfig:
    transport_mode: ExtensionTransportMode
    package_path: Path | None
    native_host_manifest: Path | None


@dataclass(frozen=True, slots=True)
class TraceConfig:
    level: TraceLevel


@dataclass(frozen=True, slots=True)
class VisionConfig:
    enabled: bool


@dataclass(frozen=True, slots=True)
class BrowskiConfig:
    agent: AgentConfig
    reasoning: ReasoningConfig
    decision: DecisionConfig
    privacy: PrivacyConfig
    safety: SafetyConfig
    extension: ExtensionConfig
    traces: TraceConfig
    vision: VisionConfig


_EXPECTED_KEYS: dict[str, set[str]] = {
    "agent": {"orchestrator"},
    "reasoning": {"provider", "model", "enabled"},
    "decision": {
        "provider",
        "mode",
        "jev_enabled",
        "laya_endpoint",
        "shadow_telemetry",
    },
    "privacy": {"mode"},
    "safety": {"confirm_high_risk_actions"},
    "extension": {"transport_mode", "package_path", "native_host_manifest"},
    "traces": {"level"},
    "vision": {"enabled"},
}


def _section(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"Configuration section [{name}] is required.")
    typed_value = cast(dict[str, object], value)
    extras = set(typed_value) - _EXPECTED_KEYS[name]
    if extras:
        extra = ", ".join(sorted(extras))
        raise ConfigError(f"Unknown key(s) in [{name}]: {extra}.")
    return typed_value


def _string(section: Mapping[str, object], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{key}' must be a non-empty string.")
    return value.strip()


def _boolean(section: Mapping[str, object], key: str) -> bool:
    value = section.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"'{key}' must be true or false.")
    return value


def _enum_value[EnumValue: StrEnum](
    enum_type: type[EnumValue],
    value: str,
    key: str,
) -> EnumValue:
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ConfigError(f"'{key}' must be one of: {allowed}.") from exc


def _optional_path(section: Mapping[str, object], key: str) -> Path | None:
    value = section.get(key, "")
    if not isinstance(value, str):
        raise ConfigError(f"'{key}' must be a path string.")
    if not value.strip():
        return None
    return Path(value).expanduser()


def parse_config(document: Mapping[str, object]) -> BrowskiConfig:
    """Validate an untrusted TOML mapping and return its typed configuration."""
    extras = set(document) - set(_EXPECTED_KEYS)
    if extras:
        extra = ", ".join(sorted(extras))
        raise ConfigError(f"Unknown top-level section(s): {extra}.")

    agent = _section(document, "agent")
    reasoning = _section(document, "reasoning")
    decision = _section(document, "decision")
    privacy = _section(document, "privacy")
    safety = _section(document, "safety")
    extension = _section(document, "extension")
    traces = _section(document, "traces")
    vision = _section(document, "vision")

    mode = _enum_value(DecisionMode, _string(decision, "mode"), "decision.mode")
    privacy_mode = _enum_value(PrivacyMode, _string(privacy, "mode"), "privacy.mode")
    transport_mode = _enum_value(
        ExtensionTransportMode,
        _string(extension, "transport_mode"),
        "extension.transport_mode",
    )
    trace_level = _enum_value(TraceLevel, _string(traces, "level"), "traces.level")
    provider_name = _enum_value(
        DecisionProviderName,
        _string(decision, "provider"),
        "decision.provider",
    )

    jev_enabled = _boolean(decision, "jev_enabled")
    if mode == DecisionMode.SHADOW and jev_enabled:
        raise ConfigError("Jev cannot be enabled while the decision provider is shadow-only.")
    if (
        provider_name in (DecisionProviderName.JEV, DecisionProviderName.ADAPTIVE)
        and not jev_enabled
    ):
        raise ConfigError("Jev-backed decision providers require decision.jev_enabled = true.")

    return BrowskiConfig(
        agent=AgentConfig(orchestrator=_string(agent, "orchestrator")),
        reasoning=ReasoningConfig(
            provider=_string(reasoning, "provider"),
            model=_string(reasoning, "model"),
            enabled=_boolean(reasoning, "enabled"),
        ),
        decision=DecisionConfig(
            provider=provider_name,
            mode=mode,
            jev_enabled=jev_enabled,
            laya_endpoint=_string(decision, "laya_endpoint"),
            shadow_telemetry=_boolean(decision, "shadow_telemetry"),
        ),
        privacy=PrivacyConfig(mode=privacy_mode),
        safety=SafetyConfig(
            confirm_high_risk_actions=_boolean(safety, "confirm_high_risk_actions")
        ),
        extension=ExtensionConfig(
            transport_mode=transport_mode,
            package_path=_optional_path(extension, "package_path"),
            native_host_manifest=_optional_path(extension, "native_host_manifest"),
        ),
        traces=TraceConfig(level=trace_level),
        vision=VisionConfig(enabled=_boolean(vision, "enabled")),
    )


def load_config(path: Path | None = None) -> BrowskiConfig:
    """Load an explicit TOML file, BROWSKI_CONFIG, or the packaged defaults."""
    selected_path = path
    if selected_path is None:
        configured_path = os.environ.get("BROWSKI_CONFIG")
        if configured_path:
            selected_path = Path(configured_path).expanduser()

    try:
        if selected_path is None:
            text = files("browser_agent.cli").joinpath("default.toml").read_text(encoding="utf-8")
        else:
            text = selected_path.expanduser().read_text(encoding="utf-8")
        document = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        source = str(selected_path) if selected_path else "packaged defaults"
        raise ConfigError(f"Could not load {source}: {exc}") from exc

    return parse_config(document)
