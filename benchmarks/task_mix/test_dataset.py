"""Explicit corpus loading preserves labels and refuses malformed inputs."""

import json
from pathlib import Path

import pytest

from benchmarks.task_mix.dataset import load_case_file, load_cases


def _write_case(path: Path) -> None:
    case = load_cases("development")[0]
    path.write_text(json.dumps(case.as_dict()) + "\n", encoding="utf-8")


def test_explicit_corpus_preserves_gold(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    _write_case(path)

    cases = load_case_file(path)

    assert cases == (load_cases("development")[0],)


def test_duplicate_case_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    _write_case(path)
    path.write_text(path.read_text() * 2, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate case IDs"):
        load_case_file(path)


def test_empty_corpus_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="1–100 cases"):
        load_case_file(path)


def test_invalid_case_identifies_source_line(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    _write_case(path)
    path.write_text(path.read_text() + "{broken\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"corpus.jsonl:2"):
        load_case_file(path)


def test_oversize_corpus_is_rejected_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    path.write_bytes(b" " * (3 * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match="3 MiB"):
        load_case_file(path)
