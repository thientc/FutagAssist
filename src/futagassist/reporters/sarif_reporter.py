"""SARIF reporter: write function info, crashes, and coverage in SARIF 2.1 format."""

from __future__ import annotations

import json
from pathlib import Path

from futagassist.core.schema import CrashInfo, CoverageReport, FunctionInfo

_SARIF_VERSION = "2.1.0"
_SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json"
_TOOL_NAME = "FutagAssist"


class SarifReporter:
    """Reporter that writes SARIF 2.1 output for crashes and function analysis."""

    format_name: str = "sarif"

    def report_functions(self, functions: list[FunctionInfo], output: Path) -> None:
        """Write function info as SARIF notifications (informational results)."""
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        results = []
        for fn in functions:
            result = {
                "ruleId": "futagassist/function-info",
                "level": "note",
                "message": {"text": f"Function: {fn.signature}"},
                "locations": [_location(fn.file_path, fn.line)],
                "properties": {
                    "name": fn.name,
                    "return_type": fn.return_type,
                    "parameters": fn.parameters,
                    "is_api": fn.is_api,
                    "is_fuzz_target_candidate": fn.is_fuzz_target_candidate,
                },
            }
            results.append(result)

        sarif = _sarif_envelope(results, rule_id="futagassist/function-info", rule_desc="Extracted function information")
        output.write_text(json.dumps(sarif, indent=2), encoding="utf-8")

    def report_crashes(self, crashes: list[CrashInfo], output: Path) -> None:
        """Write crash info as SARIF error results."""
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        results = []
        for crash in crashes:
            result = {
                "ruleId": f"futagassist/crash/{crash.warn_class.lower() or 'unknown'}",
                "level": "error",
                "message": {"text": crash.summary or f"Crash: {crash.warn_class}"},
                "locations": [_location(crash.crash_file, crash.crash_line)] if crash.crash_file else [],
                "properties": {
                    "warn_class": crash.warn_class,
                    "artifact_path": crash.artifact_path,
                },
            }
            if crash.backtrace:
                result["properties"]["backtrace"] = crash.backtrace
            results.append(result)

        sarif = _sarif_envelope(results, rule_id="futagassist/crash", rule_desc="Fuzzer crash report")
        output.write_text(json.dumps(sarif, indent=2), encoding="utf-8")

    def report_coverage(self, data: CoverageReport, output: Path) -> None:
        """Write coverage summary as SARIF informational result."""
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        pct = (data.lines_covered / data.lines_total * 100) if data.lines_total else 0.0
        result = {
            "ruleId": "futagassist/coverage",
            "level": "note",
            "message": {
                "text": f"Coverage: {data.lines_covered}/{data.lines_total} lines ({pct:.1f}%)"
            },
            "properties": {
                "binary_path": data.binary_path,
                "lines_covered": data.lines_covered,
                "lines_total": data.lines_total,
                "regions_covered": data.regions_covered,
                "regions_total": data.regions_total,
            },
        }

        sarif = _sarif_envelope([result], rule_id="futagassist/coverage", rule_desc="Code coverage summary")
        output.write_text(json.dumps(sarif, indent=2), encoding="utf-8")


def _location(file_path: str, line: int) -> dict:
    """Build a SARIF location object."""
    loc: dict = {
        "physicalLocation": {
            "artifactLocation": {"uri": file_path},
        }
    }
    if line > 0:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return loc


def _sarif_envelope(results: list[dict], rule_id: str, rule_desc: str) -> dict:
    """Wrap results in a SARIF 2.1 envelope."""
    return {
        "version": _SARIF_VERSION,
        "$schema": _SARIF_SCHEMA,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": _TOOL_NAME,
                        "informationUri": "https://github.com/example/FutagAssist",
                        "rules": [
                            {
                                "id": rule_id,
                                "shortDescription": {"text": rule_desc},
                            },
                        ],
                    }
                },
                "results": results,
            }
        ],
    }
