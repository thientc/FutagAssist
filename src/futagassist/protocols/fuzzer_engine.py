"""Protocol for fuzzing engines."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from futagassist.core.schema import CrashInfo, CoverageReport, FuzzResult


class FuzzerEngine(Protocol):
    """Protocol for fuzzing engines (libFuzzer, AFL++, Honggfuzz)."""

    name: str

    def fuzz(
        self,
        binary: Path,
        corpus_dir: Path,
        **options: object,
    ) -> FuzzResult:
        """Run the fuzzer on a binary with optional corpus."""
        ...

    def get_coverage(self, binary: Path, profdata: Path) -> CoverageReport:
        """Generate coverage report from profdata."""
        ...

    def parse_crashes(self, artifact_dir: Path) -> list[CrashInfo]:
        """Parse crash artifacts from a directory."""
        ...
