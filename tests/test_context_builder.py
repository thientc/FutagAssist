"""Tests for context builder."""

from __future__ import annotations

from pathlib import Path

from futagassist.analysis.context_builder import enrich_functions
from futagassist.core.schema import FunctionInfo


def test_enrich_functions_empty_list() -> None:
    """enrich_functions with empty list returns empty list."""
    assert enrich_functions([], Path("/repo")) == []


def test_enrich_functions_no_file_path_unchanged(tmp_path: Path) -> None:
    """Functions without file_path or line are returned unchanged."""
    f = FunctionInfo(name="foo", signature="void foo()", file_path="", line=0)
    out = enrich_functions([f], tmp_path)
    assert len(out) == 1
    assert out[0].context == ""


def test_enrich_functions_adds_context_from_file(tmp_path: Path) -> None:
    """When file_path and line are set, context is filled from source file."""
    src = tmp_path / "src" / "lib.c"
    src.parent.mkdir(parents=True, exist_ok=True)
    lines = ["line1", "line2", "line3", "line4", "line5", "line6", "line7", "line8", "line9", "line10"]
    src.write_text("\n".join(lines))
    f = FunctionInfo(name="bar", signature="int bar()", file_path="src/lib.c", line=5)
    out = enrich_functions([f], tmp_path, before_lines=2, after_lines=2)
    assert len(out) == 1
    assert "line3" in out[0].context
    assert "line5" in out[0].context
    assert "line7" in out[0].context


def test_enrich_functions_missing_file_unchanged(tmp_path: Path) -> None:
    """When source file does not exist, function is returned with unchanged context."""
    f = FunctionInfo(name="x", signature="void x()", file_path="missing.c", line=1)
    out = enrich_functions([f], tmp_path)
    assert len(out) == 1
    assert out[0].context == ""
