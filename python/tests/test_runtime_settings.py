"""Typed extension settings stay constrained and persist without changing other TOML."""

from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import pytest

from browser_agent.cli.config import (
    ConfigError,
    DecisionMode,
    DecisionProviderName,
    PrivacyMode,
    ReasoningEffort,
    RuntimeLayaMode,
    TraceLevel,
    load_config,
    load_runtime_settings,
    update_runtime_settings,
)


def _settings(
    *,
    effort: str = "low",
    privacy_mode: str = "standard",
    laya_mode: str = "shadow",
    trace_level: str = "standard",
) -> dict[str, object]:
    return {
        "effort": effort,
        "privacyMode": privacy_mode,
        "layaMode": laya_mode,
        "traceLevel": trace_level,
    }


def test_runtime_settings_are_typed_from_the_current_config() -> None:
    settings = load_runtime_settings()

    assert settings.effort is ReasoningEffort.LOW
    assert settings.privacy_mode is PrivacyMode.STANDARD
    assert settings.laya_mode is RuntimeLayaMode.SHADOW
    assert settings.trace_level is TraceLevel.STANDARD
    assert settings.confirm_high_risk_actions is True
    assert settings.extension_transport.value == "native_host"


def test_runtime_settings_update_is_atomic_private_and_preserves_other_config(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    source = (Path(__file__).parents[1] / "src/browser_agent/cli/default.toml").read_text(
        encoding="utf-8"
    )
    source = source.replace('orchestrator = "langgraph"', 'orchestrator = "langgraph" # keep me')
    config_path.write_text(source, encoding="utf-8")

    settings = update_runtime_settings(
        _settings(
            effort="none",
            privacy_mode="privacy_first",
            laya_mode="disabled",
            trace_level="detailed",
        ),
        config_path,
    )

    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert parsed["agent"]["orchestrator"] == "langgraph"
    assert "# keep me" in config_path.read_text(encoding="utf-8")
    assert parsed["reasoning"]["effort"] == "none"
    assert parsed["privacy"]["mode"] == "privacy_first"
    assert parsed["decision"]["provider"] == "laya"
    assert parsed["decision"]["mode"] == "disabled"
    assert parsed["decision"]["jev_enabled"] is False
    assert parsed["decision"]["shadow_telemetry"] is False
    assert parsed["traces"]["level"] == "detailed"
    assert parsed["safety"]["confirm_high_risk_actions"] is True
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert settings.effort is ReasoningEffort.NONE
    assert settings.privacy_mode is PrivacyMode.PRIVACY_FIRST
    assert settings.laya_mode is RuntimeLayaMode.DISABLED
    assert settings.trace_level is TraceLevel.DETAILED
    assert settings.extension_transport.value == "native_host"

    effective_config = load_config(config_path)
    assert effective_config.decision.provider is DecisionProviderName.LAYA
    assert effective_config.decision.mode is DecisionMode.DISABLED


def test_default_user_config_is_loaded_after_first_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))

    update_runtime_settings(_settings(privacy_mode="offline"))

    config = load_config()
    assert config.privacy.mode is PrivacyMode.OFFLINE
    assert config.reasoning.effort is ReasoningEffort.LOW
    assert (tmp_path / "config-home/browski/config.toml").is_file()


def test_panel_settings_require_cli_config_to_enable_supported_trace_detail(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    source = (Path(__file__).parents[1] / "src/browser_agent/cli/default.toml").read_text(
        encoding="utf-8"
    )
    config_path.write_text(
        source.replace('level = "standard"', 'level = "off"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Trace detail is disabled in the CLI"):
        load_runtime_settings(config_path)


@pytest.mark.parametrize(
    "values",
    [
        _settings(effort="high"),
        _settings(privacy_mode="unknown"),
        _settings(laya_mode="active"),
        {**_settings(), "unknown": "value"},
        {"effort": "low"},
    ],
)
def test_runtime_settings_reject_unsupported_values_without_writing(
    tmp_path: Path,
    values: dict[str, object],
) -> None:
    config_path = tmp_path / "missing" / "config.toml"

    with pytest.raises(ConfigError):
        update_runtime_settings(values, config_path)

    assert not config_path.exists()


def test_runtime_settings_reject_a_symbolic_link_config(tmp_path: Path) -> None:
    real_config = tmp_path / "real.toml"
    link_config = tmp_path / "link.toml"
    real_config.write_text("untouched", encoding="utf-8")
    link_config.symlink_to(real_config)

    with pytest.raises(ConfigError, match="symbolic-link"):
        update_runtime_settings(_settings(), link_config)

    assert real_config.read_text(encoding="utf-8") == "untouched"


def test_atomic_writer_does_not_leave_world_readable_files(tmp_path: Path) -> None:
    target = tmp_path / "browski" / "config.toml"
    update_runtime_settings(_settings(), target)

    assert not stat.S_IMODE(target.stat().st_mode) & (stat.S_IRGRP | stat.S_IROTH)
