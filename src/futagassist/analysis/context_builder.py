"""Context builder: enrich FunctionInfo with surrounding code context for harness generation."""

from __future__ import annotations

from pathlib import Path

from futagassist.core.schema import FunctionInfo


def enrich_functions(
    functions: list[FunctionInfo],
    repo_path: Path,
    *,
    before_lines: int = 5,
    after_lines: int = 15,
) -> list[FunctionInfo]:
    """
    Enrich each function with context (surrounding source lines) when file_path and line are set.

    Reads the source file and sets FunctionInfo.context to lines [line - before_lines : line + after_lines].
    If the file cannot be read or path is missing, leaves context unchanged.
    """
    repo_path = Path(repo_path).resolve()
    result: list[FunctionInfo] = []
    for f in functions:
        if not f.file_path or f.line <= 0:
            result.append(f)
            continue
        src = repo_path / f.file_path if not Path(f.file_path).is_absolute() else Path(f.file_path)
        if not src.is_file():
            result.append(f)
            continue
        try:
            lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            result.append(f)
            continue
        one_based = f.line  # FunctionInfo.line is 1-based
        start = max(0, one_based - 1 - before_lines)
        end = min(len(lines), one_based + after_lines)  # include line and after_lines following
        context = "\n".join(lines[start:end]) if start < end else ""
        result.append(f.model_copy(update={"context": context or f.context}))
    return result
