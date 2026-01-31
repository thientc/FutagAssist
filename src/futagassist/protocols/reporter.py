"""Protocol for output formats."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from futagassist.core.schema import CrashInfo, CoverageReport, FunctionInfo


class Reporter(Protocol):
    """Protocol for output formats (JSON, SARIF, HTML, SVRES)."""

    format_name: str

    def report_coverage(self, data: CoverageReport, output: Path) -> None:
        """Write coverage report to output path."""
        ...

    def report_crashes(self, crashes: list[CrashInfo], output: Path) -> None:
        """Write crash report to output path."""
        ...

    def report_functions(self, functions: list[FunctionInfo], output: Path) -> None:
        """Write function info report to output path."""
        ...
