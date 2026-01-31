"""JSON reporter: write function info, coverage, and crashes as JSON."""

from __future__ import annotations

import json
from pathlib import Path

from futagassist.core.schema import CrashInfo, CoverageReport, FunctionInfo, UsageContext


class JsonReporter:
    """Reporter that writes JSON output for functions, usage contexts, coverage, and crashes."""

    format_name: str = "json"

    def report_analysis(
        self,
        functions: list[FunctionInfo],
        usage_contexts: list[UsageContext],
        output: Path,
    ) -> None:
        """Write functions and usage contexts to a single JSON file for the analyze stage."""
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "functions": [f.model_dump() for f in functions],
            "usage_contexts": [u.model_dump() for u in usage_contexts],
        }
        output.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def report_functions(self, functions: list[FunctionInfo], output: Path) -> None:
        """Write function list as a JSON array to the output path."""
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        data = [f.model_dump() for f in functions]
        output.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def report_coverage(self, data: CoverageReport, output: Path) -> None:
        """Write coverage report as JSON to the output path."""
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data.model_dump(), indent=2), encoding="utf-8")

    def report_crashes(self, crashes: list[CrashInfo], output: Path) -> None:
        """Write crash list as a JSON array to the output path."""
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        data = [c.model_dump() for c in crashes]
        output.write_text(json.dumps(data, indent=2), encoding="utf-8")
