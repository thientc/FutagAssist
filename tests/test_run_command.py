"""Tests for 'futagassist run' command and integration helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from futagassist.cli import (
    _format_duration,
    _print_pipeline_summary,
    _print_stage_result,
    main,
)
from futagassist.core.schema import (
    CrashInfo,
    FuzzResult,
    PipelineResult,
    StageResult,
)


# ── helpers ──────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_mock_stage(name: str, *, success: bool = True, message: str = "") -> MagicMock:
    """Create a mock stage that returns a predetermined StageResult."""
    stage = MagicMock()
    stage.can_skip = MagicMock(return_value=False)
    stage.execute = MagicMock(
        return_value=StageResult(stage_name=name, success=success, message=message, data={})
    )
    return stage


# ── _format_duration ─────────────────────────────────────────────────────


class TestFormatDuration:
    def test_seconds_only(self) -> None:
        assert _format_duration(5.3) == "5.3s"

    def test_zero(self) -> None:
        assert _format_duration(0.0) == "0.0s"

    def test_minutes_and_seconds(self) -> None:
        assert _format_duration(125.0) == "2m 5s"

    def test_just_under_minute(self) -> None:
        assert _format_duration(59.9) == "59.9s"

    def test_exact_minute(self) -> None:
        assert _format_duration(60.0) == "1m 0s"

    def test_large_duration(self) -> None:
        result = _format_duration(3661.0)
        assert "61m" in result


# ── _print_stage_result ──────────────────────────────────────────────────


class TestPrintStageResult:
    def test_success_printed_to_stdout(self, capsys) -> None:
        r = StageResult(stage_name="build", success=True, message="ok")
        _print_stage_result(r, 1.5)
        out = capsys.readouterr().out
        assert "✓" in out
        assert "build" in out
        assert "OK" in out
        assert "1.5s" in out

    def test_failure_printed_to_stderr(self, capsys) -> None:
        r = StageResult(stage_name="fuzz", success=False, message="crashed")
        _print_stage_result(r, 2.0)
        err = capsys.readouterr().err
        assert "✗" in err
        assert "FAILED" in err
        assert "fuzz" in err


# ── _print_pipeline_summary ─────────────────────────────────────────────


class TestPrintPipelineSummary:
    def test_all_success(self, capsys) -> None:
        pr = PipelineResult(
            success=True,
            stage_results=[
                StageResult(stage_name="build", success=True, message="done"),
                StageResult(stage_name="analyze", success=True, message="done"),
            ],
        )
        _print_pipeline_summary(pr, 10.5)
        out = capsys.readouterr().out
        assert "Pipeline Summary" in out
        assert "2 succeeded" in out
        assert "0 failed" in out
        assert "SUCCESS" in out
        assert "10.5s" in out

    def test_with_skipped(self, capsys) -> None:
        pr = PipelineResult(
            success=True,
            stage_results=[
                StageResult(stage_name="build", success=True, message="done"),
                StageResult(stage_name="fuzz_build", success=True, message="skipped (in skip_stages)"),
            ],
        )
        _print_pipeline_summary(pr, 5.0)
        out = capsys.readouterr().out
        assert "1 succeeded" in out
        assert "1 skipped" in out
        assert "0 failed" in out

    def test_with_failure(self, capsys) -> None:
        pr = PipelineResult(
            success=False,
            stage_results=[
                StageResult(stage_name="build", success=True, message="done"),
                StageResult(stage_name="analyze", success=False, message="error"),
            ],
        )
        _print_pipeline_summary(pr, 3.0)
        out = capsys.readouterr().out
        assert "1 succeeded" in out
        assert "1 failed" in out
        assert "FAILED" in out

    def test_with_crashes(self, capsys) -> None:
        pr = PipelineResult(
            success=True,
            stage_results=[StageResult(stage_name="fuzz", success=True)],
            fuzz_results=[
                FuzzResult(crashes=[CrashInfo(summary="c1"), CrashInfo(summary="c2")]),
                FuzzResult(crashes=[CrashInfo(summary="c3")]),
            ],
        )
        _print_pipeline_summary(pr, 1.0)
        out = capsys.readouterr().out
        assert "Crashes found: 3" in out

    def test_displays_db_path(self, capsys) -> None:
        pr = PipelineResult(
            success=True,
            stage_results=[StageResult(stage_name="build", success=True)],
            db_path=Path("/tmp/codeql-db"),
        )
        _print_pipeline_summary(pr, 1.0)
        out = capsys.readouterr().out
        assert "CodeQL DB" in out
        assert "codeql-db" in out

    def test_displays_harness_dir(self, capsys) -> None:
        pr = PipelineResult(
            success=True,
            stage_results=[StageResult(stage_name="generate", success=True)],
            fuzz_targets_dir=Path("/tmp/targets"),
        )
        _print_pipeline_summary(pr, 1.0)
        out = capsys.readouterr().out
        assert "Harnesses" in out

    def test_displays_binaries_dir(self, capsys) -> None:
        pr = PipelineResult(
            success=True,
            stage_results=[StageResult(stage_name="compile", success=True)],
            binaries_dir=Path("/tmp/bins"),
        )
        _print_pipeline_summary(pr, 1.0)
        out = capsys.readouterr().out
        assert "Binaries" in out


# ── run command CLI ──────────────────────────────────────────────────────


class TestRunCommand:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--stages" in result.output
        assert "--skip" in result.output
        assert "--no-llm" in result.output
        assert "--no-stop-on-failure" in result.output
        assert "full fuzzing pipeline" in result.output.lower()

    def test_requires_repo(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["run"])
        assert result.exit_code != 0

    def test_nonexistent_repo(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["run", "--repo", "/nonexistent/path_abc"])
        assert result.exit_code != 0

    def test_all_stages_succeed(self, runner: CliRunner, tmp_path: Path) -> None:
        """When all stages succeed, run exits 0 with SUCCESS."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        mock_stages = {
            name: _make_mock_stage(name)
            for name in ["build", "analyze", "generate", "fuzz_build", "compile", "fuzz", "report"]
        }

        def mock_get_stage(name):
            return mock_stages[name]

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = list(mock_stages.keys())
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = mock_get_stage
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path)],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, result.output
        assert "SUCCESS" in result.output
        assert "Pipeline Summary" in result.output
        # All 7 stages should have been called
        for stage in mock_stages.values():
            stage.execute.assert_called_once()

    def test_skip_stages(self, runner: CliRunner, tmp_path: Path) -> None:
        """With --skip fuzz_build,fuzz, those stages are skipped."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        stage_names = ["build", "analyze", "generate", "fuzz_build", "compile", "fuzz", "report"]
        mock_stages = {name: _make_mock_stage(name) for name in stage_names}

        def mock_get_stage(name):
            return mock_stages[name]

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = stage_names
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = mock_get_stage
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--skip", "fuzz_build,fuzz"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, result.output
        # Skipped stages should NOT have execute called
        mock_stages["fuzz_build"].execute.assert_not_called()
        mock_stages["fuzz"].execute.assert_not_called()
        # Others should
        mock_stages["build"].execute.assert_called_once()
        mock_stages["report"].execute.assert_called_once()
        # Output shows skipped
        assert "2 skipped" in result.output

    def test_specific_stages_only(self, runner: CliRunner, tmp_path: Path) -> None:
        """With --stages build,analyze only those stages run."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        mock_stages = {
            "build": _make_mock_stage("build"),
            "analyze": _make_mock_stage("analyze"),
        }

        def mock_get_stage(name):
            return mock_stages[name]

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["build", "analyze"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = mock_get_stage
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "build,analyze"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, result.output
        assert "2 succeeded" in result.output
        assert "build" in result.output
        assert "analyze" in result.output

    def test_stop_on_failure(self, runner: CliRunner, tmp_path: Path) -> None:
        """Default: pipeline stops on first failure."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        mock_stages = {
            "build": _make_mock_stage("build", success=False, message="build failed"),
            "analyze": _make_mock_stage("analyze"),
        }

        def mock_get_stage(name):
            return mock_stages[name]

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["build", "analyze"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = mock_get_stage
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "build,analyze"],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        # analyze should NOT run after build failure
        mock_stages["analyze"].execute.assert_not_called()
        assert "FAILED" in result.output

    def test_no_stop_on_failure(self, runner: CliRunner, tmp_path: Path) -> None:
        """With --no-stop-on-failure, pipeline continues past failures."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        mock_stages = {
            "build": _make_mock_stage("build", success=False, message="build failed"),
            "analyze": _make_mock_stage("analyze"),
        }

        def mock_get_stage(name):
            return mock_stages[name]

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["build", "analyze"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = mock_get_stage
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "build,analyze", "--no-stop-on-failure"],
                catch_exceptions=False,
            )

        assert result.exit_code == 1  # overall fails
        # But analyze DID run
        mock_stages["analyze"].execute.assert_called_once()

    def test_no_llm_flag(self, runner: CliRunner, tmp_path: Path) -> None:
        """--no-llm sets use_llm=False in context config."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        captured_ctx = []

        def capture_stage(name):
            stage = MagicMock()
            stage.can_skip = MagicMock(return_value=False)

            def execute(ctx):
                captured_ctx.append(ctx)
                return StageResult(stage_name=name, success=True)

            stage.execute = execute
            return stage

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["build"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = lambda name: capture_stage(name)
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "build", "--no-llm"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert len(captured_ctx) == 1
        assert captured_ctx[0].config["use_llm"] is False
        assert captured_ctx[0].config["compile_use_llm"] is False

    def test_verbose_flag(self, runner: CliRunner, tmp_path: Path) -> None:
        """--verbose / -v shows LLM: disabled and verbose info."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = []
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "", "-v"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "SUCCESS" in result.output

    def test_can_skip_stage(self, runner: CliRunner, tmp_path: Path) -> None:
        """When a stage's can_skip returns True, it is skipped."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        stage = MagicMock()
        stage.can_skip = MagicMock(return_value=True)
        stage.execute = MagicMock()  # should not be called

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["build"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = MagicMock(return_value=stage)
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "build"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        stage.execute.assert_not_called()
        assert "skipped" in result.output.lower()

    def test_stage_not_found(self, runner: CliRunner, tmp_path: Path) -> None:
        """When registry can't find a stage, the error is handled."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["nonexistent"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = MagicMock(side_effect=KeyError("nonexistent"))
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "nonexistent"],
                catch_exceptions=False,
            )

        # Should fail because stage not found and stop_on_failure=True
        assert result.exit_code == 1

    def test_stage_exception(self, runner: CliRunner, tmp_path: Path) -> None:
        """When a stage raises an exception, it is caught and reported."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        stage = MagicMock()
        stage.can_skip = MagicMock(return_value=False)
        stage.execute = MagicMock(side_effect=RuntimeError("boom"))

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["build"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = MagicMock(return_value=stage)
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "build"],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "boom" in result.output

    def test_progress_headers(self, runner: CliRunner, tmp_path: Path) -> None:
        """Progress headers show [idx/total] Stage: name."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        mock_stages = {
            "build": _make_mock_stage("build"),
            "analyze": _make_mock_stage("analyze"),
        }

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["build", "analyze"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = lambda name: mock_stages[name]
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "build,analyze"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "[1/2] Stage: build" in result.output
        assert "[2/2] Stage: analyze" in result.output

    def test_output_dir_option(self, runner: CliRunner, tmp_path: Path) -> None:
        """--output sets report_output in context config."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        out_dir = tmp_path / "my_output"

        captured_ctx = []

        def capture_stage(name):
            stage = MagicMock()
            stage.can_skip = MagicMock(return_value=False)

            def execute(ctx):
                captured_ctx.append(ctx)
                return StageResult(stage_name=name, success=True)

            stage.execute = execute
            return stage

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = ["report"]
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_registry.get_stage = lambda name: capture_stage(name)
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path), "--stages", "report", "--output", str(out_dir)],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert len(captured_ctx) == 1
        assert "reports" in captured_ctx[0].config["report_output"]

    def test_header_output(self, runner: CliRunner, tmp_path: Path) -> None:
        """Run command header shows FutagAssist version, repo, language, stages."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        with patch("futagassist.cli._load_env_and_plugins") as mock_load:
            mock_config = MagicMock()
            mock_config.config.pipeline.stages = []
            mock_config.config.pipeline.skip_stages = []
            mock_config.config.pipeline.stop_on_failure = True
            mock_config.config.llm_provider = "openai"
            mock_config.config.fuzzer_engine = "libfuzzer"
            mock_config.config.fuzzer.max_total_time = 60
            mock_config.config.fuzzer.timeout = 10
            mock_config.config.fuzzer.fork = 1
            mock_config.config.fuzzer.rss_limit_mb = 2048

            mock_registry = MagicMock()
            mock_load.return_value = (mock_config, mock_registry)

            result = runner.invoke(
                main,
                ["run", "--repo", str(tmp_path)],
                catch_exceptions=False,
            )

        assert "FutagAssist" in result.output
        assert "Repository:" in result.output
        assert "Language: cpp" in result.output
        assert "LLM: openai" in result.output
        assert "Fuzzer: libfuzzer" in result.output
