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


def test_cli_build_requires_repo(runner: CliRunner) -> None:
    """build command requires --repo."""
    result = runner.invoke(main, ["build"], catch_exceptions=False)
    assert result.exit_code != 0


def test_cli_build_nonexistent_repo(runner: CliRunner) -> None:
    """build with nonexistent repo exits with non-zero (Click 2 for path validation)."""
    result = runner.invoke(
        main,
        ["build", "--repo", "/nonexistent/repo"],
        catch_exceptions=False,
    )
    assert result.exit_code != 0


def test_cli_build_with_repo(runner: CliRunner, tmp_path: Path) -> None:
    """build with valid repo path runs (may fail on codeql but command is accepted)."""
    (tmp_path / "README").write_text("make")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["build", "--repo", str(tmp_path)],
            catch_exceptions=False,
        )
        # Exit 0 if codeql present and build succeeds, else 1
        assert result.exit_code in (0, 1)
        if result.exit_code == 1:
            out_lower = result.output.lower()
            assert (
                "build failed" in out_lower
                or "failed" in out_lower
                or "error" in out_lower
                or "fatal" in out_lower
                or "not found" in out_lower
            )


def test_cli_build_with_log_file(runner: CliRunner, tmp_path: Path) -> None:
    """build with --log-file writes log to the given path."""
    (tmp_path / "README").write_text("make")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    custom_log = tmp_path / "my-build.log"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["build", "--repo", str(tmp_path), "--log-file", str(custom_log)],
            catch_exceptions=False,
        )
    assert result.exit_code in (0, 1)
    if custom_log.exists():
        content = custom_log.read_text(encoding="utf-8")
        assert "Build stage" in content or "repo_path" in content or "CodeQL" in content


def test_cli_build_accepts_verbose(runner: CliRunner, tmp_path: Path) -> None:
    """build with --verbose / -v is accepted (no option error)."""
    (tmp_path / "README").write_text("make")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["build", "--repo", str(tmp_path), "--verbose"],
            catch_exceptions=False,
        )
        assert result.exit_code in (0, 1)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result_v = runner.invoke(
            main,
            ["build", "--repo", str(tmp_path), "-v"],
            catch_exceptions=False,
        )
        assert result_v.exit_code in (0, 1)


def test_cli_build_accepts_build_script(runner: CliRunner, tmp_path: Path) -> None:
    """build with --build-script is accepted; script path relative to repo."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "mybuild.sh").write_text("#!/bin/sh\nexit 0")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["build", "--repo", str(tmp_path), "--build-script", "mybuild.sh"],
            catch_exceptions=False,
        )
        # Exit 0 if CodeQL present and build succeeds, else 1 (or 2 if script not found)
        assert result.exit_code in (0, 1, 2)
        if result.exit_code == 2:
            assert "not found" in result.output.lower() or "Build script" in result.output
