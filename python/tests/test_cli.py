"""CLI wiring contracts that do not require a browser or provider credentials."""

from importlib import import_module

from typer.testing import CliRunner

from browser_agent.cli.main import app

cli_main = import_module("browser_agent.cli.main")


def test_resume_cli_exposes_sqlite_and_confirmation_options() -> None:
    result = CliRunner().invoke(app, ["resume", "--help"])

    assert result.exit_code == 0
    assert "checkpoint database" in result.stdout
    assert "--approve" in result.stdout
    assert "--deny" in result.stdout


def test_run_cli_routes_to_autonomous_task_command(monkeypatch) -> None:
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
