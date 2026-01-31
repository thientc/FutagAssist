"""Tests for JSON reporter."""

from __future__ import annotations

import json
from pathlib import Path

from futagassist.core.schema import CoverageReport, CrashInfo, FunctionInfo, UsageContext
from futagassist.reporters.json_reporter import JsonReporter


def test_json_reporter_report_analysis(tmp_path: Path) -> None:
    """report_analysis writes functions and usage_contexts to a single JSON file."""
    out = tmp_path / "analysis.json"
    reporter = JsonReporter()
    functions = [FunctionInfo(name="f1", signature="void f1()")]
    usage_contexts = [
        UsageContext(name="seq1", calls=["init", "process", "cleanup"]),
    ]
    reporter.report_analysis(functions, usage_contexts, out)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert "functions" in data
    assert len(data["functions"]) == 1
    assert data["functions"][0]["name"] == "f1"
    assert "usage_contexts" in data
    assert len(data["usage_contexts"]) == 1
    assert data["usage_contexts"][0]["calls"] == ["init", "process", "cleanup"]


def test_json_reporter_report_functions(tmp_path: Path) -> None:
    """report_functions writes a JSON array of function dicts."""
    out = tmp_path / "out" / "functions.json"
    reporter = JsonReporter()
    functions = [
        FunctionInfo(name="f1", signature="void f1()", file_path="a.c", line=10),
        FunctionInfo(name="f2", signature="int f2(int x)", parameters=["int x"], return_type="int"),
    ]
    reporter.report_functions(functions, out)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert len(data) == 2
    assert data[0]["name"] == "f1"
    assert data[0]["line"] == 10
    assert data[1]["name"] == "f2"
    assert data[1]["return_type"] == "int"


def test_json_reporter_report_coverage(tmp_path: Path) -> None:
    """report_coverage writes JSON for CoverageReport."""
    out = tmp_path / "coverage.json"
    reporter = JsonReporter()
    cov = CoverageReport(binary_path="/bin/fuzz", lines_covered=100, lines_total=200)
    reporter.report_coverage(cov, out)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["binary_path"] == "/bin/fuzz"
    assert data["lines_covered"] == 100


def test_json_reporter_report_crashes(tmp_path: Path) -> None:
    """report_crashes writes a JSON array of crash dicts."""
    out = tmp_path / "crashes.json"
    reporter = JsonReporter()
    crashes = [CrashInfo(artifact_path="crash-1", summary="SIGSEGV")]
    reporter.report_crashes(crashes, out)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert len(data) == 1
    assert data[0]["summary"] == "SIGSEGV"
