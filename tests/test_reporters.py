"""Tests for reporter plugins (JSON, SARIF, HTML)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import CoverageReport, CrashInfo, FunctionInfo
from futagassist.reporters import register_builtin_reporters


def _sample_functions() -> list[FunctionInfo]:
    return [
        FunctionInfo(name="foo", signature="int foo(int x)", file_path="src/foo.c", line=10, is_api=True),
        FunctionInfo(name="bar", signature="void bar()", file_path="src/bar.c", line=20, is_fuzz_target_candidate=True),
    ]


def _sample_crashes() -> list[CrashInfo]:
    return [
        CrashInfo(crash_file="src/foo.c", crash_line=42, warn_class="ASAN", summary="heap-buffer-overflow"),
        CrashInfo(artifact_path="/tmp/crash-abc", warn_class="CRASH", summary="unknown crash"),
    ]


def _sample_coverage() -> CoverageReport:
    return CoverageReport(
        binary_path="/bin/fuzz_foo",
        profdata_path="/tmp/default.profdata",
        lines_covered=50,
        lines_total=100,
        regions_covered=30,
        regions_total=60,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_reporters_registered(self) -> None:
        reg = ComponentRegistry()
        register_builtin_reporters(reg)
        reporters = reg.list_available()["reporters"]
        assert "json" in reporters
        assert "sarif" in reporters
        assert "html" in reporters


# ---------------------------------------------------------------------------
# JSON reporter
# ---------------------------------------------------------------------------


class TestJsonReporter:
    def test_report_functions(self, tmp_path: Path) -> None:
        from futagassist.reporters.json_reporter import JsonReporter

        r = JsonReporter()
        out = tmp_path / "functions.json"
        r.report_functions(_sample_functions(), out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data) == 2
        assert data[0]["name"] == "foo"

    def test_report_crashes(self, tmp_path: Path) -> None:
        from futagassist.reporters.json_reporter import JsonReporter

        r = JsonReporter()
        out = tmp_path / "crashes.json"
        r.report_crashes(_sample_crashes(), out)

        data = json.loads(out.read_text())
        assert len(data) == 2
        assert data[0]["warn_class"] == "ASAN"

    def test_report_coverage(self, tmp_path: Path) -> None:
        from futagassist.reporters.json_reporter import JsonReporter

        r = JsonReporter()
        out = tmp_path / "coverage.json"
        r.report_coverage(_sample_coverage(), out)

        data = json.loads(out.read_text())
        assert data["lines_covered"] == 50
        assert data["lines_total"] == 100


# ---------------------------------------------------------------------------
# SARIF reporter
# ---------------------------------------------------------------------------


class TestSarifReporter:
    def test_report_functions(self, tmp_path: Path) -> None:
        from futagassist.reporters.sarif_reporter import SarifReporter

        r = SarifReporter()
        out = tmp_path / "functions.sarif"
        r.report_functions(_sample_functions(), out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert data["version"] == "2.1.0"
        assert len(data["runs"]) == 1
        results = data["runs"][0]["results"]
        assert len(results) == 2
        assert results[0]["ruleId"] == "futagassist/function-info"
        assert results[0]["level"] == "note"

    def test_report_crashes(self, tmp_path: Path) -> None:
        from futagassist.reporters.sarif_reporter import SarifReporter

        r = SarifReporter()
        out = tmp_path / "crashes.sarif"
        r.report_crashes(_sample_crashes(), out)

        data = json.loads(out.read_text())
        results = data["runs"][0]["results"]
        assert len(results) == 2
        assert results[0]["level"] == "error"
        assert "asan" in results[0]["ruleId"]
        # First crash has location
        assert len(results[0]["locations"]) == 1
        loc = results[0]["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/foo.c"
        assert loc["region"]["startLine"] == 42

    def test_report_coverage(self, tmp_path: Path) -> None:
        from futagassist.reporters.sarif_reporter import SarifReporter

        r = SarifReporter()
        out = tmp_path / "coverage.sarif"
        r.report_coverage(_sample_coverage(), out)

        data = json.loads(out.read_text())
        results = data["runs"][0]["results"]
        assert len(results) == 1
        assert "50/100" in results[0]["message"]["text"]
        assert "50.0%" in results[0]["message"]["text"]

    def test_sarif_schema_present(self, tmp_path: Path) -> None:
        from futagassist.reporters.sarif_reporter import SarifReporter

        r = SarifReporter()
        out = tmp_path / "test.sarif"
        r.report_functions([], out)

        data = json.loads(out.read_text())
        assert "$schema" in data
        assert "sarif-schema" in data["$schema"]


# ---------------------------------------------------------------------------
# HTML reporter
# ---------------------------------------------------------------------------


class TestHtmlReporter:
    def test_report_functions(self, tmp_path: Path) -> None:
        from futagassist.reporters.html_reporter import HtmlReporter

        r = HtmlReporter()
        out = tmp_path / "functions.html"
        r.report_functions(_sample_functions(), out)

        assert out.exists()
        html = out.read_text()
        assert "<!DOCTYPE html>" in html
        assert "foo" in html
        assert "bar" in html
        assert "badge-api" in html  # foo is API
        assert "badge-fuzz" in html  # bar is fuzz candidate

    def test_report_crashes(self, tmp_path: Path) -> None:
        from futagassist.reporters.html_reporter import HtmlReporter

        r = HtmlReporter()
        out = tmp_path / "crashes.html"
        r.report_crashes(_sample_crashes(), out)

        html = out.read_text()
        assert "heap-buffer-overflow" in html
        assert "badge-crash" in html
        assert "ASAN" in html

    def test_report_coverage(self, tmp_path: Path) -> None:
        from futagassist.reporters.html_reporter import HtmlReporter

        r = HtmlReporter()
        out = tmp_path / "coverage.html"
        r.report_coverage(_sample_coverage(), out)

        html = out.read_text()
        assert "50/100" in html
        assert "50.0%" in html
        assert "progress-bar" in html
        assert "progress-fill" in html

    def test_report_coverage_zero(self, tmp_path: Path) -> None:
        from futagassist.reporters.html_reporter import HtmlReporter

        r = HtmlReporter()
        out = tmp_path / "coverage.html"
        r.report_coverage(CoverageReport(), out)

        html = out.read_text()
        assert "0/0" in html

    def test_html_escapes_special_chars(self, tmp_path: Path) -> None:
        from futagassist.reporters.html_reporter import HtmlReporter

        r = HtmlReporter()
        funcs = [FunctionInfo(name="foo<bar>", signature='int foo<bar>(const char* "x")')]
        out = tmp_path / "functions.html"
        r.report_functions(funcs, out)

        html = out.read_text()
        assert "&lt;bar&gt;" in html
        assert "&quot;" in html
        assert "<bar>" not in html  # raw angle brackets should be escaped

    def test_report_empty_functions(self, tmp_path: Path) -> None:
        from futagassist.reporters.html_reporter import HtmlReporter

        r = HtmlReporter()
        out = tmp_path / "functions.html"
        r.report_functions([], out)

        html = out.read_text()
        assert "0 function(s)" in html
