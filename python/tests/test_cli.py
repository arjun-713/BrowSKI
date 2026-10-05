"""CLI wiring contracts that do not require a browser or provider credentials."""

from typer.testing import CliRunner

from browser_agent.cli.main import app


def test_resume_cli_exposes_sqlite_and_confirmation_options() -> None:
    result = CliRunner().invoke(app, ["resume", "--help"])

    assert result.exit_code == 0
    assert "checkpoint database" in result.stdout
    assert "--approve" in result.stdout
    assert "--deny" in result.stdout
