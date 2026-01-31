"""Protocol for language-specific analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from futagassist.core.schema import FunctionInfo


class LanguageAnalyzer(Protocol):
    """Protocol for language-specific analysis (C/C++, Python, Java, Go)."""

    language: str

    def get_codeql_queries(self) -> list[Path]:
        """Return paths to CodeQL query files for this language."""
        ...

    def extract_functions(self, db_path: Path) -> list[FunctionInfo]:
        """Extract function information from a CodeQL database."""
        ...

    def generate_harness_template(self, func: FunctionInfo) -> str:
        """Return a harness template for the given function."""
        ...

    def get_compiler_flags(self) -> list[str]:
        """Return compiler flags for building fuzz targets."""
        ...
