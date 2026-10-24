"""Typed TOML configuration for the local BROWSKI CLI."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import cast

from browser_agent.decisions.task_sites import DEFAULT_SITE_ALIASES, validate_site_aliases
from browser_agent.reasoning.contracts import ReasoningEffort
from browser_agent.telemetry.debug_log import DebugLogConfig


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


class ExecutionEngine(StrEnum):
    FAST = "fast"
    GENERAL = "general"
    LEGACY = "legacy"


class SearchEngine(StrEnum):
    """Engine for General's search action; Google suits the user's own profile."""

    GOOGLE = "google"
    BING = "bing"
    DUCKDUCKGO = "duckduckgo"


class FastProviderName(StrEnum):
    LAYA = "laya"
    JEV = "jev"


class TextProviderName(StrEnum):
    DISABLED = "disabled"
    OPENAI = "openai"


@dataclass(frozen=True, slots=True)
class AgentConfig:
    orchestrator: str
    engine: ExecutionEngine = ExecutionEngine.GENERAL
    fast_provider: FastProviderName = FastProviderName.LAYA
    text_provider: TextProviderName = TextProviderName.OPENAI
    allow_paid_api: bool = True
    text_model: str = "gpt-6-luna"
    laya_checkpoint: str = ".browser-data/laya-browser-v19s"
    jev_endpoint: str = "https://api.typesafe.ai/v1/systemone"

    general_max_steps: int = 60
    general_max_calls: int = 150
    general_timeout_seconds: int = 1800
    general_max_failures: int = 3
    general_step_timeout: int = 180
    general_search_engine: SearchEngine = SearchEngine.GOOGLE
    # "none" made precise multi-step work (e.g. configurators) unreliable live.
    general_reasoning_effort: ReasoningEffort = ReasoningEffort.LOW


@dataclass(frozen=True, slots=True)
class ReasoningConfig:
    provider: str
    model: str
    enabled: bool
    effort: ReasoningEffort


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
class BrowserCodeConfig:
    enabled: bool = False


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
    browser_code: BrowserCodeConfig = BrowserCodeConfig()
    debug: DebugLogConfig = DebugLogConfig()
    site_aliases: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_SITE_ALIASES))


class RuntimeLayaMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    effort: ReasoningEffort
    privacy_mode: PrivacyMode
    laya_mode: RuntimeLayaMode
    trace_level: TraceLevel
    confirm_high_risk_actions: bool
    extension_transport: ExtensionTransportMode
    engine: ExecutionEngine = ExecutionEngine.GENERAL
    fast_provider: FastProviderName = FastProviderName.LAYA
    text_provider: TextProviderName = TextProviderName.OPENAI
    allow_paid_api: bool = True
    text_model: str = "gpt-6-luna"
    laya_checkpoint: str = ".browser-data/laya-browser-v19s"
    jev_endpoint: str = "https://api.typesafe.ai/v1/systemone"


_EXPECTED_KEYS: dict[str, set[str]] = {
    "agent": {
        "orchestrator",
        "engine",
        "fast_provider",
        "text_provider",
        "allow_paid_api",
        "text_model",
        "laya_checkpoint",
        "jev_endpoint",
        "general_max_steps",
        "general_max_calls",
        "general_timeout_seconds",
        "general_max_failures",
        "general_step_timeout",
        "general_search_engine",
        "general_reasoning_effort",
    },
    "reasoning": {"provider", "model", "enabled", "effort"},
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
    "browser_code": {"enabled"},
    "debug": {"enabled", "directory", "max_session_bytes", "max_sessions", "retention_days"},
    "navigation": {"site_aliases"},
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


def _engine_options(agent: Mapping[str, object]) -> AgentConfig:
    """Honor explicit engine choices; missing keys use the ADR-032 product defaults."""
    defaults = AgentConfig(orchestrator=_string(agent, "orchestrator"))

    def text(key: str, default: str) -> str:
        value = _string({key: agent.get(key, default)}, key)
        if len(value) > 1_000:
            raise ConfigError(f"'agent.{key}' exceeds the supported length.")
        return value

    def budget(key: str, default: int, minimum: int, maximum: int) -> int:
        value = agent.get(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ConfigError(f"'agent.{key}' must be an integer between {minimum} and {maximum}.")
        return value

    endpoint = text("jev_endpoint", defaults.jev_endpoint)
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(endpoint)
    except ValueError as error:
        raise ConfigError("Invalid agent.jev_endpoint URL.") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("'agent.jev_endpoint' must be HTTPS without embedded credentials.")
    return AgentConfig(
        orchestrator=defaults.orchestrator,
        engine=_enum_value(ExecutionEngine, text("engine", defaults.engine), "agent.engine"),
        fast_provider=_enum_value(
            FastProviderName, text("fast_provider", defaults.fast_provider), "agent.fast_provider"
        ),
        text_provider=_enum_value(
            TextProviderName, text("text_provider", defaults.text_provider), "agent.text_provider"
        ),
        allow_paid_api=_boolean(
            {"allow_paid_api": agent.get("allow_paid_api", defaults.allow_paid_api)},
            "allow_paid_api",
        ),
        text_model=text("text_model", defaults.text_model),
        laya_checkpoint=text("laya_checkpoint", defaults.laya_checkpoint),
        jev_endpoint=endpoint,
        general_max_steps=budget("general_max_steps", defaults.general_max_steps, 1, 200),
        general_max_calls=budget("general_max_calls", defaults.general_max_calls, 1, 500),
        general_timeout_seconds=budget(
            "general_timeout_seconds", defaults.general_timeout_seconds, 5, 7200
        ),
        general_max_failures=budget("general_max_failures", defaults.general_max_failures, 1, 10),
        general_step_timeout=budget(
            "general_step_timeout", defaults.general_step_timeout, 120, 600
        ),
        general_search_engine=_enum_value(
            SearchEngine,
            text("general_search_engine", defaults.general_search_engine),
            "agent.general_search_engine",
        ),
        general_reasoning_effort=_enum_value(
            ReasoningEffort,
            text("general_reasoning_effort", defaults.general_reasoning_effort),
            "agent.general_reasoning_effort",
        ),
    )


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
    browser_code_value = document.get("browser_code")
    if browser_code_value is None:
        browser_code_enabled = False
    elif not isinstance(browser_code_value, dict):
        raise ConfigError("Configuration section [browser_code] must be a table.")
    else:
        browser_code = cast(dict[str, object], browser_code_value)
        extras = set(browser_code) - _EXPECTED_KEYS["browser_code"]
        if extras:
            extra = ", ".join(sorted(extras))
            raise ConfigError(f"Unknown key(s) in [browser_code]: {extra}.")
        browser_code_enabled = _boolean(browser_code, "enabled")

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
    confirm_high_risk_actions = _boolean(safety, "confirm_high_risk_actions")
    if not confirm_high_risk_actions:
        raise ConfigError("'safety.confirm_high_risk_actions' must stay true.")
    if mode == DecisionMode.SHADOW and jev_enabled:
        raise ConfigError("Jev cannot be enabled while the decision provider is shadow-only.")
    if (
        provider_name in (DecisionProviderName.JEV, DecisionProviderName.ADAPTIVE)
        and not jev_enabled
    ):
        raise ConfigError("Jev-backed decision providers require decision.jev_enabled = true.")

    effort_value = reasoning.get("effort", ReasoningEffort.LOW.value)
    if not isinstance(effort_value, str):
        raise ConfigError("'reasoning.effort' must be a string.")
    if effort_value not in {ReasoningEffort.NONE.value, ReasoningEffort.LOW.value}:
        raise ConfigError("'reasoning.effort' must be 'none' or 'low'.")

    return BrowskiConfig(
        agent=_engine_options(agent),
        reasoning=ReasoningConfig(
            provider=_string(reasoning, "provider"),
            model=_string(reasoning, "model"),
            enabled=_boolean(reasoning, "enabled"),
            effort=_enum_value(
                ReasoningEffort,
                effort_value,
                "reasoning.effort",
            ),
        ),
        decision=DecisionConfig(
            provider=provider_name,
            mode=mode,
            jev_enabled=jev_enabled,
            laya_endpoint=_string(decision, "laya_endpoint"),
            shadow_telemetry=_boolean(decision, "shadow_telemetry"),
        ),
        privacy=PrivacyConfig(mode=privacy_mode),
        safety=SafetyConfig(confirm_high_risk_actions=confirm_high_risk_actions),
        extension=ExtensionConfig(
            transport_mode=transport_mode,
            package_path=_optional_path(extension, "package_path"),
            native_host_manifest=_optional_path(extension, "native_host_manifest"),
        ),
        traces=TraceConfig(level=trace_level),
        vision=VisionConfig(enabled=_boolean(vision, "enabled")),
        browser_code=BrowserCodeConfig(enabled=browser_code_enabled),
        debug=_parse_debug_config(document),
        site_aliases=_parse_site_aliases(document),
    )


def _parse_site_aliases(document: Mapping[str, object]) -> dict[str, str]:
    if "navigation" not in document:
        return dict(DEFAULT_SITE_ALIASES)
    section = _section(document, "navigation")
    try:
        return validate_site_aliases(section.get("site_aliases", DEFAULT_SITE_ALIASES))
    except ValueError as error:
        raise ConfigError("Invalid navigation.site_aliases configuration.") from error


def _parse_debug_config(document: Mapping[str, object]) -> DebugLogConfig:
    if "debug" not in document:
        return DebugLogConfig()
    section = _section(document, "debug")
    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("'debug.enabled' must be true or false.")

    def integer(key: str, default: int) -> int:
        value = section.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"'debug.{key}' must be an integer.")
        return value

    try:
        return DebugLogConfig(
            enabled=enabled,
            directory=_optional_path(section, "directory") or Path("debug-logs"),
            max_session_bytes=integer("max_session_bytes", 16 * 1024 * 1024),
            max_sessions=integer("max_sessions", 100),
            retention_days=integer("retention_days", 30),
        )
    except ValueError as error:
        raise ConfigError("Invalid debug logging limits.") from error


def load_config(path: Path | None = None) -> BrowskiConfig:
    """Load an explicit TOML file, configured user file, or packaged defaults."""
    selected_path = path
    if selected_path is None:
        configured_path = os.environ.get("BROWSKI_CONFIG")
        if configured_path:
            selected_path = Path(configured_path).expanduser()
        elif default_user_config_path().is_file():
            selected_path = default_user_config_path()

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


def default_user_config_path() -> Path:
    """Return the user-owned config path used for extension settings updates."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "browski" / "config.toml"


def load_runtime_settings(path: Path | None = None) -> RuntimeSettings:
    """Return the small settings surface supported by the extension panel."""
    config = load_config(path)
    if config.traces.level == TraceLevel.OFF:
        raise ConfigError(
            "Trace detail is disabled in the CLI configuration; set traces.level to "
            "'standard' or 'detailed' before using extension runtime settings."
        )
    laya_enabled = (
        config.decision.provider == DecisionProviderName.LAYA
        and config.decision.mode == DecisionMode.SHADOW
        and config.decision.shadow_telemetry
    )
    return RuntimeSettings(
        effort=config.reasoning.effort,
        privacy_mode=config.privacy.mode,
        laya_mode=RuntimeLayaMode.SHADOW if laya_enabled else RuntimeLayaMode.DISABLED,
        trace_level=config.traces.level,
        confirm_high_risk_actions=config.safety.confirm_high_risk_actions,
        extension_transport=config.extension.transport_mode,
        engine=config.agent.engine,
        fast_provider=config.agent.fast_provider,
        text_provider=config.agent.text_provider,
        allow_paid_api=config.agent.allow_paid_api,
        text_model=config.agent.text_model,
        laya_checkpoint=config.agent.laya_checkpoint,
        jev_endpoint=config.agent.jev_endpoint,
    )


def update_runtime_settings(
    settings: Mapping[str, object],
    path: Path | None = None,
) -> RuntimeSettings:
    """Validate and atomically persist editable runtime settings."""
    required = {"effort", "privacyMode", "layaMode", "traceLevel"}
    optional = {
        "engine",
        "fastProvider",
        "textProvider",
        "allowPaidApi",
        "textModel",
        "layaCheckpoint",
        "jevEndpoint",
    }
    if not required <= set(settings) or set(settings) - (required | optional):
        raise ConfigError("Runtime settings contain unsupported or missing fields.")

    effort = _enum_value(
        ReasoningEffort,
        _mapping_string(settings, "effort"),
        "reasoning.effort",
    )
    privacy_mode = _enum_value(
        PrivacyMode,
        _mapping_string(settings, "privacyMode"),
        "privacy.mode",
    )
    laya_mode = _enum_value(
        RuntimeLayaMode,
        _mapping_string(settings, "layaMode"),
        "decision.laya_mode",
    )
    trace_level = _enum_value(
        TraceLevel,
        _mapping_string(settings, "traceLevel"),
        "traces.level",
    )
    if trace_level == TraceLevel.OFF:
        raise ConfigError("'traceLevel' must be 'standard' or 'detailed'.")

    target = _settings_target_path(path)
    if target.is_symlink():
        raise ConfigError("Runtime settings cannot replace a symbolic-link config file.")
    if target.is_file():
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Could not read {target}: {exc}") from exc
    else:
        text = files("browser_agent.cli").joinpath("default.toml").read_text(encoding="utf-8")

    # Validate the existing file before changing it, so unrelated invalid config
    # is not silently rewritten or hidden from the user.
    document = tomllib.loads(text)
    config = parse_config(document)
    agent_updates = {
        "engine": settings.get("engine", config.agent.engine.value),
        "fast_provider": settings.get("fastProvider", config.agent.fast_provider.value),
        "text_provider": settings.get("textProvider", config.agent.text_provider.value),
        "allow_paid_api": settings.get("allowPaidApi", config.agent.allow_paid_api),
        "text_model": settings.get("textModel", config.agent.text_model),
        "laya_checkpoint": settings.get("layaCheckpoint", config.agent.laya_checkpoint),
        "jev_endpoint": settings.get("jevEndpoint", config.agent.jev_endpoint),
    }
    _engine_options({"orchestrator": config.agent.orchestrator, **agent_updates})
    for key, value in agent_updates.items():
        serialized = ("true" if value else "false") if isinstance(value, bool) else cast(str, value)
        text = _set_toml_value(text, "agent", key, serialized)
    laya_shadow = laya_mode == RuntimeLayaMode.SHADOW
    updates = (
        ("reasoning", "effort", effort.value),
        ("privacy", "mode", privacy_mode.value),
        ("decision", "provider", DecisionProviderName.LAYA.value),
        (
            "decision",
            "mode",
            DecisionMode.SHADOW.value if laya_shadow else DecisionMode.DISABLED.value,
        ),
        ("decision", "jev_enabled", "false"),
        ("decision", "shadow_telemetry", "true" if laya_shadow else "false"),
        ("safety", "confirm_high_risk_actions", "true"),
        ("traces", "level", trace_level.value),
    )
    for section, key, value in updates:
        text = _set_toml_value(text, section, key, value)

    # Validate the complete resulting document before the atomic replacement.
    updated_document = tomllib.loads(text)
    parse_config(updated_document)
    _atomic_private_write(target, text)
    return load_runtime_settings(target)


def _mapping_string(settings: Mapping[str, object], key: str) -> str:
    value = settings.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"Runtime setting '{key}' must be a string.")
    return value


def _settings_target_path(path: Path | None) -> Path:
    if path is not None:
        return path.expanduser()
    configured_path = os.environ.get("BROWSKI_CONFIG")
    if configured_path:
        return Path(configured_path).expanduser()
    return default_user_config_path()


def _set_toml_value(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    section_pattern = re.compile(rf"^\s*\[{re.escape(section)}\]\s*(?:#.*)?$")
    next_section_pattern = re.compile(r"^\s*\[[^]]+\]")
    key_pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)")
    section_start = next(
        (index for index, line in enumerate(lines) if section_pattern.match(line.rstrip("\r\n"))),
        None,
    )
    if section_start is None:
        raise ConfigError(f"Configuration section [{section}] is required.")
    section_end = next(
        (
            index
            for index in range(section_start + 1, len(lines))
            if next_section_pattern.match(lines[index])
        ),
        len(lines),
    )

    for index in range(section_start + 1, section_end):
        match = key_pattern.match(lines[index])
        if match is None:
            continue
        line = lines[index]
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        content = line[: -len(newline)] if newline else line
        _, comment_separator, comment = content.partition("#")
        suffix = f"  #{comment}" if comment_separator else ""
        encoded_value = (
            value if value in {"true", "false"} else json.dumps(value, ensure_ascii=False)
        )
        lines[index] = f"{match.group(1)}{encoded_value}{suffix}{newline}"
        return "".join(lines)

    encoded_value = value if value in {"true", "false"} else json.dumps(value, ensure_ascii=False)
    lines.insert(section_end, f"{key} = {encoded_value}\n")
    return "".join(lines)


def _atomic_private_write(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise ConfigError(f"Could not persist runtime settings to {path}: {exc}") from exc
