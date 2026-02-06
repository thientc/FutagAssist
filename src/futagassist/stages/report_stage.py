"""Report stage: generate output reports from pipeline results using Reporter plugins."""

from __future__ import annotations

import logging
from pathlib import Path

from futagassist.core.schema import (
    CoverageReport,
    CrashInfo,
    FunctionInfo,
    PipelineContext,
    StageResult,
)

log = logging.getLogger(__name__)


class ReportStage:
    """Pipeline stage that generates output reports using registered Reporter plugins.

    Produces reports for:
    - **Functions**: Extracted function info from the analyze stage
    - **Crashes**: Deduplicated crash information from the fuzz stage
    - **Coverage**: Aggregated coverage data from the fuzz stage

    Delegates to all registered Reporter plugins (JSON, SARIF, HTML, etc.)
    or a specific list of formats via ``report_formats`` in context config.
    """

    name = "report"
    depends_on: list[str] = ["fuzz"]

    def execute(self, context: PipelineContext) -> StageResult:
        """Generate reports from pipeline context."""
        registry = context.config.get("registry")
        config_manager = context.config.get("config_manager")
        if not registry or not config_manager:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="registry or config_manager not set in context.config",
            )

        avail = registry.list_available()
        available_reporters = avail.get("reporters", [])
        if not available_reporters:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="No reporter plugins registered.",
            )

        # Which formats to use
        requested_formats = context.config.get("report_formats")
        if requested_formats:
            formats = [f for f in requested_formats if f in available_reporters]
            missing = [f for f in requested_formats if f not in available_reporters]
            if missing:
                log.warning("Requested report formats not available: %s", missing)
        else:
            formats = list(available_reporters)

        if not formats:
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"None of the requested formats are available. Registered: {available_reporters}",
            )

        # Output directory
        output_dir = context.config.get("report_output")
        if output_dir:
            output_dir = Path(output_dir)
        elif context.results_dir:
            output_dir = Path(context.results_dir) / "reports"
        elif context.repo_path:
            output_dir = Path(context.repo_path) / "reports"
        else:
            output_dir = Path.cwd() / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Gather data from context
        functions = context.functions
        crashes = self._gather_crashes(context)
        coverage = self._gather_coverage(context)

        written_files: list[str] = []
        errors: list[str] = []

        for fmt in formats:
            try:
                reporter = registry.get_reporter(fmt)
            except Exception as e:
                errors.append(f"Failed to instantiate reporter {fmt!r}: {e}")
                continue

            fmt_dir = output_dir / fmt
            fmt_dir.mkdir(parents=True, exist_ok=True)

            # Functions report
            if functions:
                try:
                    out_path = fmt_dir / f"functions.{_ext(fmt)}"
                    reporter.report_functions(functions, out_path)
                    written_files.append(str(out_path))
                    log.info("Wrote functions report: %s", out_path)
                except Exception as e:
                    errors.append(f"{fmt}: report_functions failed: {e}")
                    log.warning("report_functions failed for %s: %s", fmt, e)

            # Crashes report
            if crashes:
                try:
                    out_path = fmt_dir / f"crashes.{_ext(fmt)}"
                    reporter.report_crashes(crashes, out_path)
                    written_files.append(str(out_path))
                    log.info("Wrote crashes report: %s", out_path)
                except Exception as e:
                    errors.append(f"{fmt}: report_crashes failed: {e}")
                    log.warning("report_crashes failed for %s: %s", fmt, e)

            # Coverage report
            if coverage:
                try:
                    out_path = fmt_dir / f"coverage.{_ext(fmt)}"
                    reporter.report_coverage(coverage, out_path)
                    written_files.append(str(out_path))
                    log.info("Wrote coverage report: %s", out_path)
                except Exception as e:
                    errors.append(f"{fmt}: report_coverage failed: {e}")
                    log.warning("report_coverage failed for %s: %s", fmt, e)

        if not written_files and not errors:
            return StageResult(
                stage_name=self.name,
                success=True,
                message="No data to report (no functions, crashes, or coverage).",
                data={"report_output": str(output_dir)},
            )

        data: dict = {
            "report_output": str(output_dir),
            "written_files": written_files,
            "report_formats": formats,
        }
        if errors:
            data["errors"] = errors

        return StageResult(
            stage_name=self.name,
            success=len(written_files) > 0,
            message=(
                f"Generated {len(written_files)} report file(s) in {len(formats)} format(s)."
                + (f" {len(errors)} error(s)." if errors else "")
            ),
            data=data,
        )

    @staticmethod
    def _gather_crashes(context: PipelineContext) -> list[CrashInfo]:
        """Collect crashes from fuzz results or fuzz stage data."""
        crashes: list[CrashInfo] = []

        # From fuzz_results on context
        for fr in context.fuzz_results:
            crashes.extend(fr.crashes)

        # From fuzz stage result data (deduplicated crashes)
        if not crashes:
            for sr in context.stage_results:
                if sr.stage_name == "fuzz" and sr.data.get("crashes"):
                    raw = sr.data["crashes"]
                    for item in raw:
                        if isinstance(item, CrashInfo):
                            crashes.append(item)
                        elif isinstance(item, dict):
                            crashes.append(CrashInfo.model_validate(item))

        return crashes

    @staticmethod
    def _gather_coverage(context: PipelineContext) -> CoverageReport | None:
        """Aggregate coverage from fuzz results (pick the one with most data)."""
        best: CoverageReport | None = None
        for fr in context.fuzz_results:
            if fr.coverage:
                if best is None or fr.coverage.lines_total > best.lines_total:
                    best = fr.coverage
        return best

    def can_skip(self, context: PipelineContext) -> bool:
        """Can skip if results_dir already contains report files."""
        if context.results_dir and Path(context.results_dir).is_dir():
            reports_dir = Path(context.results_dir) / "reports"
            if reports_dir.is_dir():
                return any(reports_dir.rglob("*.*"))
        return False


def _ext(fmt: str) -> str:
    """Map reporter format name to file extension."""
    extensions = {
        "json": "json",
        "sarif": "sarif",
        "html": "html",
        "svres": "svres",
        "csv": "csv",
    }
    return extensions.get(fmt, fmt)
