"""CLI wiring contracts that do not require a browser or provider credentials."""

import asyncio
import json
import sqlite3
import tomllib
from dataclasses import replace
from importlib import import_module
from importlib.metadata import distribution
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from browser_agent.cli.config import (
    BrowskiConfig,
    ConfigError,
    DecisionMode,
    DecisionProviderName,
    ExtensionTransportMode,
    PrivacyMode,
    TraceLevel,
    load_config,
    parse_config,
)
from browser_agent.cli.doctor import CheckStatus, DoctorCheck, check_extension_bridge
from browser_agent.cli.main import app
from browser_agent.persistence import SQLiteRunMetadataStore
from browser_agent.persistence.run_metrics import RunMetrics
from browser_agent.providers.privacy import PrivacyMode as ProviderPrivacyMode

cli_main = import_module("browser_agent.cli.main")


def _default_toml() -> str:
    config_path = Path(__file__).parents[1] / "src/browser_agent/cli/default.toml"
    return config_path.read_text(encoding="utf-8")


def test_resume_cli_exposes_sqlite_and_confirmation_options() -> None:
    result = CliRunner().invoke(app, ["resume", "--help"])

    assert result.exit_code == 0
    assert "checkpoint database" in result.stdout
    assert "--approve" in result.stdout
    assert "--deny" in result.stdout


def test_serve_starts_authenticated_bridge_and_reports_task_support(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from browser_agent.extension.service import ExtensionBridgeService

    async def stop_after_start(service: ExtensionBridgeService) -> None:
        await service.close()

    monkeypatch.setattr(ExtensionBridgeService, "wait_closed", stop_after_start)
    socket_path = tmp_path / "runtime" / "bridge.sock"
    result = CliRunner().invoke(app, ["serve", "--socket-path", str(socket_path)])

    assert result.exit_code == 0, result.output
    assert "Attach a tab" in result.stdout
    assert not socket_path.exists()


def test_serve_respects_disabled_extension_transport(tmp_path: Path) -> None:
    config_path = tmp_path / "disabled.toml"
    config_path.write_text(
        _default_toml().replace('transport_mode = "native_host"', 'transport_mode = "disabled"'),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["serve", "--config", str(config_path)])

    assert result.exit_code != 0
    assert "extension transport is disabled" in result.output


def test_doctor_reports_bridge_files_without_connecting(tmp_path: Path) -> None:
    from browser_agent.extension.service import ExtensionBridgeService

    socket_path = tmp_path / "runtime" / "bridge.sock"
    service = ExtensionBridgeService(socket_path)

    asyncio.run(service.start())
    active = check_extension_bridge(socket_path)
    asyncio.run(service.close())
    stopped = check_extension_bridge(socket_path)

    assert active.status == CheckStatus.INFO
    assert "does not probe" in active.detail
    assert stopped.status == CheckStatus.WARN


def test_runs_list_does_not_create_a_missing_database(tmp_path: Path) -> None:
    database = tmp_path / "missing.sqlite3"

    result = CliRunner().invoke(app, ["runs", "list", "--database", str(database)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
    assert not database.exists()


def test_runs_list_includes_only_safe_bounded_metrics(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = SQLiteRunMetadataStore(database)
    asyncio.run(store.record_started("safe-run"))
    asyncio.run(
        store.record_metrics(
            "safe-run",
            RunMetrics(action_count=3, luna_calls=2),
            event_at="2026-10-08T00:00:01+00:00",
        )
    )

    result = CliRunner().invoke(app, ["runs", "list", "--database", str(database)])

    assert result.exit_code == 0, result.output
    run = json.loads(result.stdout)[0]
    assert run["metrics"]["action_count"] == 3
    assert run["metrics"]["luna_calls"] == 2
    assert "task" not in run
    assert "secret" not in result.stdout


def test_runs_clean_requires_apply_to_delete_metadata(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = SQLiteRunMetadataStore(database)
    asyncio.run(store.record_started("old-run"))
    asyncio.run(
        store.record_state(
            "old-run",
            status="completed",
            steps=2,
            reasoning_calls=1,
        )
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE browski_runs SET updated_at = '2020-01-01T00:00:00+00:00' "
            "WHERE run_id = 'old-run'"
        )

    preview = CliRunner().invoke(
        app,
        ["runs", "clean", "--database", str(database), "--older-than-days", "30"],
    )

    assert preview.exit_code == 0, preview.output
    preview_result = json.loads(preview.stdout)
    assert preview_result["mode"] == "preview"
    assert preview_result["run_ids"] == ["old-run"]
    assert "--apply" in preview_result["next_step"]
    assert asyncio.run(store.list_runs())[0].run_id == "old-run"

    applied = CliRunner().invoke(
        app,
        [
            "runs",
            "clean",
            "--database",
            str(database),
            "--older-than-days",
            "30",
            "--apply",
        ],
    )

    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.stdout)["mode"] == "applied"
    assert asyncio.run(store.list_runs()) == []


def test_run_cli_routes_to_autonomous_task_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_task(**options: object) -> None:
        calls.update(options)

    monkeypatch.setattr(cli_main, "task", fake_task)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "Complete the example task",
            "--start-url",
            "https://example.com",
            "--provider",
            "jev",
            "--checkpoint-db",
            "runs.sqlite",
            "--no-headless",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == {
        "goal": "Complete the example task",
        "url": "https://example.com",
        "headless": False,
        "provider": "jev",
        "checkpoint_db": "runs.sqlite",
    }


def test_observe_cli_preserves_the_browser_observation_slice() -> None:
    result = CliRunner().invoke(app, ["observe", "--help"])

    assert result.exit_code == 0
    assert "URL to navigate to and observe" in result.stdout


def test_browski_and_agent_console_scripts_are_installed_aliases() -> None:
    entry_points = {
        entry.name: entry.value
        for entry in distribution("browser-agent").entry_points
        if entry.group == "console_scripts"
    }

    assert entry_points["browski"] == "browser_agent.cli:main"
    assert entry_points["agent"] == "browser_agent.cli:main"
    assert entry_points["browski-native-host"] == "browser_agent.extension.native_host:main"
    assert entry_points["browski-install-native-host"] == "browser_agent.extension.install:main"


def test_project_declares_browski_as_the_primary_console_script() -> None:
    import tomllib

    project_file = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))

    assert project["project"]["scripts"] == {
        "browski": "browser_agent.cli:main",
        "agent": "browser_agent.cli:main",
        "browski-native-host": "browser_agent.extension.native_host:main",
        "browski-install-native-host": "browser_agent.extension.install:main",
    }


def test_default_config_is_typed_and_keeps_laya_shadow_only() -> None:
    config = load_config()

    assert config.reasoning.enabled is True
    assert config.reasoning.model == "gpt-6-luna"
    assert config.decision.provider is DecisionProviderName.LAYA
    assert config.decision.mode is DecisionMode.SHADOW
    assert config.decision.jev_enabled is False
    assert config.privacy.mode is PrivacyMode.STANDARD
    assert config.safety.confirm_high_risk_actions is True
    assert config.extension.transport_mode is ExtensionTransportMode.NATIVE_HOST
    assert config.traces.level is TraceLevel.STANDARD
    assert config.vision.enabled is False
    assert config.browser_code.enabled is False


def test_config_can_enable_browser_code_only_explicitly() -> None:
    document = tomllib.loads(_default_toml())
    assert parse_config(document).browser_code.enabled is False

    document["browser_code"]["enabled"] = True
    assert parse_config(document).browser_code.enabled is True

    del document["browser_code"]
    assert parse_config(document).browser_code.enabled is False

    document["browser_code"] = {"enabled": "true"}
    with pytest.raises(ConfigError, match="must be true or false"):
        parse_config(document)


def test_config_rejects_unknown_sections_and_jev_in_shadow_mode() -> None:
    default_toml = _default_toml()
    document = tomllib.loads(default_toml)
    document["unexpected"] = {}
    with pytest.raises(ConfigError, match="Unknown top-level section"):
        parse_config(document)

    document = tomllib.loads(default_toml)
    document["decision"]["jev_enabled"] = True
    with pytest.raises(ConfigError, match="Jev cannot be enabled"):
        parse_config(document)


def test_doctor_help_is_available_without_provider_activity() -> None:
    result = CliRunner().invoke(app, ["doctor", "--help"])

    assert result.exit_code == 0
    assert "local BROWSKI prerequisites" in result.stdout
    assert "--config" in result.stdout


def test_config_command_reports_policy_without_leaking_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-config-test-value")

    result = CliRunner().invoke(app, ["config"])

    assert result.exit_code == 0, result.output
    assert "Browser modes: managed CLI and attached extension" in result.stdout
    assert "Reasoning: openai / gpt-6-luna" in result.stdout
    assert "OpenAI key: configured" in result.stdout
    assert "Laya: shadow only" in result.stdout
    assert "Jev: disabled" in result.stdout
    assert "On-demand vision: disabled" in result.stdout
    assert "secret-config-test-value" not in result.stdout


def test_doctor_reports_policy_and_never_displays_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_laya_health(config: BrowskiConfig) -> DoctorCheck:
        return DoctorCheck(
            "Laya service",
            CheckStatus.WARN,
            "local service unavailable",
        )

    import browser_agent.cli.doctor as doctor_module

    monkeypatch.setattr(doctor_module, "_check_laya_health", fake_laya_health)
    monkeypatch.setattr(
        doctor_module,
        "_check_rust_binding",
        lambda: DoctorCheck("Rust binding", CheckStatus.PASS, "available"),
    )
    monkeypatch.setattr(
        doctor_module,
        "_check_chromium",
        lambda: DoctorCheck("Chromium", CheckStatus.PASS, "/usr/bin/chromium"),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-value")

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "OpenAI key: present; value is not displayed" in result.stdout
    assert "Laya service: local service unavailable" in result.stdout
    assert "decision provider laya (shadow); Jev disabled" in result.stdout
    assert "Luna selects executable actions" in result.stdout
    assert "Laya is non-executing shadow only" in result.stdout
    assert "secret-test-value" not in result.stdout


def test_doctor_recognizes_browski_openai_key_without_displaying_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_laya_health(config: BrowskiConfig) -> DoctorCheck:
        return DoctorCheck("Laya service", CheckStatus.WARN, "local service unavailable")

    import browser_agent.cli.doctor as doctor_module

    monkeypatch.setattr(doctor_module, "_check_laya_health", fake_laya_health)
    monkeypatch.setattr(
        doctor_module,
        "_check_rust_binding",
        lambda: DoctorCheck("Rust binding", CheckStatus.PASS, "available"),
    )
    monkeypatch.setattr(
        doctor_module,
        "_check_chromium",
        lambda: DoctorCheck("Chromium", CheckStatus.PASS, "/usr/bin/chromium"),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("BROWSKI_OPENAI_API_KEY", "secret-browski-key")

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "OpenAI key: present; value is not displayed" in result.stdout
    assert "secret-browski-key" not in result.stdout


def test_doctor_requires_browski_host_manifest_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import browser_agent.cli.doctor as doctor_module

    (tmp_path / "unrelated-host.json").write_text(
        '{"name": "org.example.host", "path": "/tmp/other-host"}',
        encoding="utf-8",
    )

    def native_host_candidates(_config: BrowskiConfig) -> list[Path]:
        return [tmp_path]

    monkeypatch.setattr(doctor_module, "_native_host_candidates", native_host_candidates)

    check = doctor_module.check_native_host(load_config())

    assert check.status is CheckStatus.INFO
    assert "not found" in check.detail


def test_doctor_finds_built_extension_manifest(tmp_path: Path) -> None:
    import browser_agent.cli.doctor as doctor_module

    manifest = tmp_path / ".output/chrome-mv3/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"manifest_version": 3}', encoding="utf-8")
    config = load_config()
    config = replace(config, extension=replace(config.extension, package_path=tmp_path))

    check = doctor_module.check_extension_package(config)

    assert check.status is CheckStatus.PASS
    assert "built MV3 manifest" in check.detail


def test_default_policy_allows_luna_with_optional_laya_shadow() -> None:
    config = load_config()

    assert cli_main._resolve_provider(None, config) == "laya"


@pytest.mark.parametrize(
    "provider",
    ["adaptive", "jev"],
)
def test_cli_rejects_jev_and_adaptive_provider_overrides(provider: str) -> None:
    with pytest.raises(typer.BadParameter, match="routing are disabled"):
        cli_main._resolve_provider(provider, load_config())


def test_privacy_modes_do_not_send_shadow_context_to_laya(tmp_path: Path) -> None:
    config_path = tmp_path / "private.toml"
    private_toml = _default_toml().replace(
        '[privacy]\nmode = "standard"',
        '[privacy]\nmode = "privacy_first"',
    )
    config_path.write_text(private_toml, encoding="utf-8")

    assert cli_main._resolve_provider(None, load_config(config_path)) is None


def test_reasoning_provider_is_wrapped_with_configured_privacy_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import browser_agent.reasoning as reasoning_module

    default_toml = _default_toml()
    config_path = tmp_path / "offline.toml"
    config_path.write_text(
        default_toml.replace('[privacy]\nmode = "standard"', '[privacy]\nmode = "offline"'),
        encoding="utf-8",
    )
    config = load_config(config_path)

    class BoundarySpy:
        def __init__(self, provider: object, *, mode: ProviderPrivacyMode) -> None:
            self.provider = provider
            self.mode = mode

    import browser_agent.providers.privacy as privacy_module

    def fake_openai_provider(*, api_key: str | None) -> object:
        _ = api_key
        return object()

    monkeypatch.setattr(privacy_module, "ProviderBoundary", BoundarySpy)
    monkeypatch.setattr(reasoning_module, "OpenAILunaProvider", fake_openai_provider)

    provider = cli_main._create_luna_reasoning_provider(config)

    assert isinstance(provider, BoundarySpy)
    assert provider.mode is ProviderPrivacyMode.OFFLINE
