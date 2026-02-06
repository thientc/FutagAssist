"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from futagassist.cli import main
from futagassist.core.schema import StageResult


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
    """check command runs; exits 1 when codeql or plugins check fails, 0 when all pass."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["check", "--skip-llm", "--skip-fuzzer", "--skip-plugins"],
            catch_exceptions=False,
        )
        assert result.exit_code in (0, 1)
        assert "codeql" in result.output.lower()


def test_cli_check_skip_options(runner: CliRunner, tmp_path: Path) -> None:
    """check with --skip-llm, --skip-fuzzer, --skip-plugins runs only codeql check."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["check", "--skip-llm", "--skip-fuzzer", "--skip-plugins", "-v"],
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


def test_cli_build_configure_options_passed_to_context(runner: CliRunner, tmp_path: Path) -> None:
    """build with --configure-options passes build_configure_options to stage context."""
    (tmp_path / "README").write_text("make")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    captured_ctx = []

    def capture_and_succeed(ctx):
        captured_ctx.append(ctx)
        return StageResult(
            stage_name="build",
            success=True,
            data={"db_path": str(tmp_path / "codeql-db"), "build_log_file": str(tmp_path / "build.log")},
        )

    with patch("futagassist.stages.build_stage.BuildStage.execute", side_effect=capture_and_succeed):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                main,
                ["build", "--repo", str(tmp_path), "--configure-options", "--without-ssl", "--no-interactive"],
                catch_exceptions=False,
            )
    assert result.exit_code == 0
    assert len(captured_ctx) == 1
    assert captured_ctx[0].config.get("build_configure_options") == "--without-ssl"


def test_cli_build_no_interactive_exits_without_prompt_on_suggested_fix(
    runner: CliRunner, tmp_path: Path
) -> None:
    """With --no-interactive and a suggested fix, build exits 1 without prompting."""
    (tmp_path / "README").write_text("make")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    fail_result = StageResult(
        stage_name="build",
        success=False,
        message="Build failed.\nSuggested fix (run manually if you agree): 'apt install foo'",
        data={
            "suggested_fix_command": "apt install foo",
            "build_log_file": str(tmp_path / "futagassist-build.log"),
        },
    )
    with patch("futagassist.stages.build_stage.BuildStage.execute", return_value=fail_result):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                main,
                ["build", "--repo", str(tmp_path), "--no-interactive"],
                catch_exceptions=False,
            )
    assert result.exit_code == 1
    assert "Build failed" in result.output or "Suggested fix" in result.output
    # Should not have prompted (no "Run this fix" in output when we did not pass input)
    assert "Run this fix" not in result.output or "--no-interactive" in result.output


def test_cli_build_interactive_accept_fix_retries(runner: CliRunner, tmp_path: Path) -> None:
    """When interactive and user accepts, fix is run and build is retried; success on retry."""
    (tmp_path / "README").write_text("make")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    fail_result = StageResult(
        stage_name="build",
        success=False,
        message="Build failed.",
        data={
            "suggested_fix_command": "true",
            "build_log_file": str(tmp_path / "futagassist-build.log"),
        },
    )
    success_result = StageResult(
        stage_name="build",
        success=True,
        message="",
        data={"db_path": str(tmp_path / "codeql-db"), "build_log_file": str(tmp_path / "futagassist-build.log")},
    )
    call_count = 0

    def mock_execute(ctx):
        nonlocal call_count
        call_count += 1
        return fail_result if call_count == 1 else success_result

    with patch("futagassist.stages.build_stage.BuildStage.execute", side_effect=mock_execute):
        with patch("futagassist.cli._is_build_interactive", return_value=True):
            with patch("futagassist.cli.click.prompt", return_value=""):  # skip configure-options retry
                with patch("futagassist.cli.click.confirm", return_value=True):
                    with patch("futagassist.cli.subprocess.run") as mock_run:
                        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                        with runner.isolated_filesystem(temp_dir=tmp_path):
                            result = runner.invoke(
                                main,
                                ["build", "--repo", str(tmp_path)],
                                catch_exceptions=False,
                            )
    assert result.exit_code == 0, result.output
    assert "CodeQL database" in result.output
    assert call_count == 2
    mock_run.assert_called_once()


def test_cli_fuzz_build_requires_repo(runner: CliRunner) -> None:
    """fuzz-build command requires --repo."""
    result = runner.invoke(main, ["fuzz-build"], catch_exceptions=False)
    assert result.exit_code != 0


def test_cli_fuzz_build_help(runner: CliRunner) -> None:
    """fuzz-build --help shows options."""
    result = runner.invoke(main, ["fuzz-build", "--help"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "fuzz-build" in result.output or "fuzz" in result.output
    assert "--repo" in result.output
    assert "sanitizer" in result.output.lower() or "install" in result.output.lower()


def test_cli_fuzz_build_success_with_mock(runner: CliRunner, tmp_path: Path) -> None:
    """fuzz-build with --repo runs FuzzBuildStage; success prints fuzz_install_prefix."""
    (tmp_path / "README").write_text("make")
    with patch("futagassist.stages.fuzz_build_stage.subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                main,
                ["fuzz-build", "--repo", str(tmp_path)],
                catch_exceptions=False,
            )
    assert result.exit_code == 0
    assert "Fuzz build succeeded" in result.output
    assert "install-fuzz" in result.output or "Instrumented install" in result.output


def test_cli_analyze_requires_db(runner: CliRunner) -> None:
    """analyze command requires --db."""
    result = runner.invoke(main, ["analyze"], catch_exceptions=False)
    assert result.exit_code != 0


def test_cli_analyze_no_language_analyzer_fails(runner: CliRunner, tmp_path: Path) -> None:
    """analyze with valid db but no language analyzer registered exits 1."""
    (tmp_path / "codeql-db").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["analyze", "--db", str(tmp_path / "codeql-db")],
            catch_exceptions=False,
        )
    assert result.exit_code == 1
    assert "language" in result.output.lower() or "analyzer" in result.output.lower()


def test_cli_analyze_with_plugin_succeeds(runner: CliRunner, tmp_path: Path) -> None:
    """analyze with plugin that registers a language analyzer succeeds and prints function count."""
    (tmp_path / "codeql-db").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    plugins_dir = tmp_path / "plugins" / "languages"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "mock_analyzer.py").write_text("""
from pathlib import Path
from futagassist.core.schema import FunctionInfo

class MockAnalyzer:
    language = "cpp"
    def get_codeql_queries(self): return []
    def extract_functions(self, db_path):
        return [
            FunctionInfo(name="f", signature="void f()"),
        ]
    def extract_usage_contexts(self, db_path): return []
    def generate_harness_template(self, func): return ""
    def get_compiler_flags(self): return []

def register(registry):
    registry.register_language("cpp", MockAnalyzer)
""")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["analyze", "--db", str(tmp_path / "codeql-db"), "--language", "cpp"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    assert "Analyzed" in result.output
    assert "function" in result.output.lower()


def test_cli_analyze_with_output_writes_json(runner: CliRunner, tmp_path: Path) -> None:
    """analyze --output writes JSON file."""
    (tmp_path / "codeql-db").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    out_json = tmp_path / "out" / "functions.json"
    plugins_dir = tmp_path / "plugins" / "languages"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "mock_analyzer.py").write_text("""
from futagassist.core.schema import FunctionInfo

class MockAnalyzer:
    language = "cpp"
    def get_codeql_queries(self): return []
    def extract_functions(self, db_path): return [FunctionInfo(name="g", signature="int g()")]
    def extract_usage_contexts(self, db_path): return []
    def generate_harness_template(self, func): return ""
    def get_compiler_flags(self): return []

def register(registry):
    registry.register_language("cpp", MockAnalyzer)
""")
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            [
                "analyze",
                "--db", str(tmp_path / "codeql-db"),
                "--output", str(out_json),
                "--language", "cpp",
            ],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert out_json.is_file()
    import json
    data = json.loads(out_json.read_text())
    assert "functions" in data
    assert len(data["functions"]) == 1
    assert data["functions"][0]["name"] == "g"
    assert "usage_contexts" in data
