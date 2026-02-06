"""Tests for ReportStage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from futagassist.core.config import ConfigManager
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import (
    CoverageReport,
    CrashInfo,
    FunctionInfo,
    FuzzResult,
    PipelineContext,
    StageResult,
)
from futagassist.stages.report_stage import ReportStage, _ext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_manager(tmp_path: Path) -> ConfigManager:
    mgr = ConfigManager(project_root=tmp_path)
    mgr._config_path = tmp_path / "nonexistent.yaml"
    mgr._env_path = tmp_path / ".env"
    mgr.load()
    return mgr


def _make_context(
    tmp_path: Path,
    functions: list[FunctionInfo] | None = None,
    fuzz_results: list[FuzzResult] | None = None,
    extra_config: dict | None = None,
) -> PipelineContext:
    registry = ComponentRegistry()
    from futagassist.stages import register_builtin_stages
    register_builtin_stages(registry)
    from futagassist.reporters import register_builtin_reporters
    register_builtin_reporters(registry)

    config_mgr = _make_config_manager(tmp_path)
    config = {
        "registry": registry,
        "config_manager": config_mgr,
        **(extra_config or {}),
    }

    return PipelineContext(
        repo_path=tmp_path,
        functions=functions or [],
        fuzz_results=fuzz_results or [],
        config=config,
    )


# ---------------------------------------------------------------------------
# Unit tests: _ext
# ---------------------------------------------------------------------------


class TestExtHelper:
    def test_known_formats(self) -> None:
        assert _ext("json") == "json"
        assert _ext("sarif") == "sarif"
        assert _ext("html") == "html"
        assert _ext("svres") == "svres"
        assert _ext("csv") == "csv"

    def test_unknown_format(self) -> None:
        assert _ext("custom") == "custom"


# ---------------------------------------------------------------------------
# ReportStage: validation
# ---------------------------------------------------------------------------


class TestReportStageValidation:
    def test_no_registry(self, tmp_path: Path) -> None:
        ctx = PipelineContext(repo_path=tmp_path, config={})
        stage = ReportStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "registry" in result.message.lower()

    def test_no_reporters_registered(self, tmp_path: Path) -> None:
        registry = ComponentRegistry()
        from futagassist.stages import register_builtin_stages
        register_builtin_stages(registry)
        # Deliberately NOT registering reporters
        config_mgr = _make_config_manager(tmp_path)
        ctx = PipelineContext(
            repo_path=tmp_path,
            config={
                "registry": registry,
                "config_manager": config_mgr,
            },
        )
        stage = ReportStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "No reporter plugins" in result.message

    def test_requested_format_not_available(self, tmp_path: Path) -> None:
        ctx = _make_context(
            tmp_path,
            functions=[FunctionInfo(name="foo", signature="void foo()")],
            extra_config={"report_formats": ["nonexistent"]},
        )
        stage = ReportStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "None of the requested formats" in result.message


# ---------------------------------------------------------------------------
# ReportStage: report generation
# ---------------------------------------------------------------------------


class TestReportStageExecution:
    def test_report_functions_json(self, tmp_path: Path) -> None:
        functions = [
            FunctionInfo(name="foo", signature="void foo(int x)"),
            FunctionInfo(name="bar", signature="int bar()"),
        ]
        output_dir = tmp_path / "reports"
        ctx = _make_context(
            tmp_path,
            functions=functions,
            extra_config={"report_output": str(output_dir)},
        )

        stage = ReportStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert len(result.data["written_files"]) >= 1
        # Verify JSON file exists and is valid
        json_path = output_dir / "json" / "functions.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert len(data) == 2
        assert data[0]["name"] == "foo"

    def test_report_crashes_json(self, tmp_path: Path) -> None:
        fuzz_results = [
            FuzzResult(
                success=True,
                crashes=[
                    CrashInfo(crash_file="x.c", crash_line=1, summary="heap-overflow"),
                    CrashInfo(crash_file="y.c", crash_line=5, summary="stack-overflow"),
                ],
            ),
        ]
        output_dir = tmp_path / "reports"
        ctx = _make_context(
            tmp_path,
            fuzz_results=fuzz_results,
            extra_config={"report_output": str(output_dir)},
        )

        stage = ReportStage()
        result = stage.execute(ctx)

        assert result.success is True
        json_path = output_dir / "json" / "crashes.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert len(data) == 2

    def test_report_coverage_json(self, tmp_path: Path) -> None:
        fuzz_results = [
            FuzzResult(
                success=True,
                coverage=CoverageReport(
                    binary_path="/bin/fuzz_foo",
                    lines_covered=50,
                    lines_total=100,
                ),
            ),
        ]
        output_dir = tmp_path / "reports"
        ctx = _make_context(
            tmp_path,
            fuzz_results=fuzz_results,
            extra_config={"report_output": str(output_dir)},
        )

        stage = ReportStage()
        result = stage.execute(ctx)

        assert result.success is True
        json_path = output_dir / "json" / "coverage.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["lines_covered"] == 50
        assert data["lines_total"] == 100

    def test_report_all_data(self, tmp_path: Path) -> None:
        """Functions + crashes + coverage produces three files."""
        functions = [FunctionInfo(name="f", signature="void f()")]
        fuzz_results = [
            FuzzResult(
                success=True,
                crashes=[CrashInfo(summary="crash1")],
                coverage=CoverageReport(lines_covered=10, lines_total=20),
            ),
        ]
        output_dir = tmp_path / "reports"
        ctx = _make_context(
            tmp_path,
            functions=functions,
            fuzz_results=fuzz_results,
            extra_config={"report_output": str(output_dir)},
        )

        stage = ReportStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert len(result.data["written_files"]) == 3

    def test_report_no_data(self, tmp_path: Path) -> None:
        """With no functions, crashes, or coverage, stage succeeds with message."""
        ctx = _make_context(tmp_path)
        stage = ReportStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert "No data to report" in result.message

    def test_report_custom_output_dir(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "custom_reports"
        ctx = _make_context(
            tmp_path,
            functions=[FunctionInfo(name="f", signature="void f()")],
            extra_config={"report_output": str(custom_dir)},
        )

        stage = ReportStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert custom_dir.is_dir()
        assert result.data["report_output"] == str(custom_dir)

    def test_report_specific_format(self, tmp_path: Path) -> None:
        """Requesting only 'json' format produces JSON output only."""
        ctx = _make_context(
            tmp_path,
            functions=[FunctionInfo(name="f", signature="void f()")],
            extra_config={"report_formats": ["json"]},
        )

        stage = ReportStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert result.data["report_formats"] == ["json"]


# ---------------------------------------------------------------------------
# ReportStage: crash gathering
# ---------------------------------------------------------------------------


class TestReportStageGatherCrashes:
    def test_gather_from_fuzz_results(self) -> None:
        ctx = PipelineContext(
            fuzz_results=[
                FuzzResult(
                    success=True,
                    crashes=[CrashInfo(summary="c1"), CrashInfo(summary="c2")],
                ),
                FuzzResult(
                    success=True,
                    crashes=[CrashInfo(summary="c3")],
                ),
            ],
        )
        crashes = ReportStage._gather_crashes(ctx)
        assert len(crashes) == 3

    def test_gather_from_stage_results(self) -> None:
        ctx = PipelineContext(
            stage_results=[
                StageResult(
                    stage_name="fuzz",
                    success=True,
                    data={
                        "crashes": [
                            {"summary": "s1", "crash_file": "a.c", "crash_line": 1},
                            {"summary": "s2"},
                        ],
                    },
                ),
            ],
        )
        crashes = ReportStage._gather_crashes(ctx)
        assert len(crashes) == 2
        assert crashes[0].summary == "s1"

    def test_gather_no_crashes(self) -> None:
        ctx = PipelineContext()
        crashes = ReportStage._gather_crashes(ctx)
        assert crashes == []


# ---------------------------------------------------------------------------
# ReportStage: coverage gathering
# ---------------------------------------------------------------------------


class TestReportStageGatherCoverage:
    def test_picks_best_coverage(self) -> None:
        ctx = PipelineContext(
            fuzz_results=[
                FuzzResult(success=True, coverage=CoverageReport(lines_total=10)),
                FuzzResult(success=True, coverage=CoverageReport(lines_total=50)),
                FuzzResult(success=True, coverage=CoverageReport(lines_total=30)),
            ],
        )
        cov = ReportStage._gather_coverage(ctx)
        assert cov is not None
        assert cov.lines_total == 50

    def test_no_coverage(self) -> None:
        ctx = PipelineContext(
            fuzz_results=[FuzzResult(success=True)],
        )
        assert ReportStage._gather_coverage(ctx) is None


# ---------------------------------------------------------------------------
# ReportStage: can_skip
# ---------------------------------------------------------------------------


class TestReportStageCanSkip:
    def test_can_skip_with_reports(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        reports_dir = results_dir / "reports" / "json"
        reports_dir.mkdir(parents=True)
        (reports_dir / "functions.json").write_text("{}")

        ctx = PipelineContext(results_dir=results_dir)
        stage = ReportStage()
        assert stage.can_skip(ctx) is True

    def test_cannot_skip_no_dir(self) -> None:
        ctx = PipelineContext()
        stage = ReportStage()
        assert stage.can_skip(ctx) is False

    def test_cannot_skip_empty_reports(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        (results_dir / "reports").mkdir(parents=True)

        ctx = PipelineContext(results_dir=results_dir)
        stage = ReportStage()
        assert stage.can_skip(ctx) is False


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestReportCLI:
    def test_cli_report_help(self) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["report", "--help"])
        assert result.exit_code == 0
        assert "--results" in result.output
        assert "--output" in result.output
        assert "--format" in result.output
        assert "--functions" in result.output

    def test_cli_report_no_data(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["report"])
        assert result.exit_code == 0
        assert "No data to report" in result.output
