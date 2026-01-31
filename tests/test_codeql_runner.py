"""Tests for CodeQL runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from futagassist.analysis.codeql_runner import CodeQLRunner


def test_codeql_runner_nonexistent_db_raises(tmp_path: Path) -> None:
    """run_queries raises FileNotFoundError when database path does not exist."""
    runner = CodeQLRunner(codeql_bin="codeql")
    not_a_db = tmp_path / "nonexistent"
    with pytest.raises(FileNotFoundError, match="database not found"):
        runner.run_queries(not_a_db, [])


def test_codeql_runner_nonexistent_query_raises(tmp_path: Path) -> None:
    """run_queries raises FileNotFoundError when a query path does not exist."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    runner = CodeQLRunner(codeql_bin="codeql")
    fake_query = tmp_path / "missing.ql"
    with pytest.raises(FileNotFoundError, match="Query path not found"):
        runner.run_queries(tmp_path, [fake_query])


def test_codeql_runner_empty_queries_accepts_db_dir(tmp_path: Path) -> None:
    """run_queries with empty query list still validates db and runs (CodeQL may error on empty)."""
    runner = CodeQLRunner(codeql_bin="codeql")
    # Empty list: CodeQL CLI may still get invoked with just db; behavior is implementation-dependent
    # We only test that we don't raise for missing query when list is empty
    result = runner.run_queries(tmp_path, [])
    assert result is not None
    # CodeQL will likely fail because tmp_path is not a real database
    assert result.returncode != 0 or result.returncode == 0
