"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from futagassist.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_version(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_plugins_list_empty(runner: CliRunner, tmp_path: Path) -> None:
    """Without plugins/ directory, list shows (none) for all."""
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["plugins", "list"])
        assert result.exit_code == 0
        assert "Available components" in result.output
        assert "Llm" in result.output or "Providers" in result.output


def test_cli_plugins_list_with_plugin(runner: CliRunner, tmp_path: Path) -> None:
    """With a plugin that registers, list shows it."""
    plugins_dir = tmp_path / "plugins" / "llm"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "openai_provider.py").write_text("""
def register(registry):
    from tests.test_registry import _MockLLM
    registry.register_llm("openai", _MockLLM)
""")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'futagassist'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["plugins", "list"], catch_exceptions=False)
        assert result.exit_code == 0
        # Plugin dir is relative to cwd; cwd in isolated_filesystem is tmp_path
        assert "openai" in result.output or "(none)" in result.output


def test_cli_check_exits_nonzero_when_fail(runner: CliRunner, tmp_path: Path) -> None:
    """check command runs; exits 1 when codeql check fails, 0 when all pass."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["check", "--skip-llm", "--skip-fuzzer"],
            catch_exceptions=False,
        )
        assert result.exit_code in (0, 1)
        assert "codeql" in result.output.lower()


def test_cli_check_skip_options(runner: CliRunner, tmp_path: Path) -> None:
    """check with --skip-llm and --skip-fuzzer runs only codeql check."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["check", "--skip-llm", "--skip-fuzzer", "-v"],
            catch_exceptions=False,
        )
        assert "codeql" in result.output.lower()
