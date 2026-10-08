"""Keep test-created application keys inside each test's temporary directory."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_application_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "application-data"))
