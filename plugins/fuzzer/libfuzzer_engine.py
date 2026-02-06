"""libFuzzer engine plugin for FutagAssist.

Register as "libfuzzer". Based on Futag's fuzzer.py design.
Runs instrumented binaries with libFuzzer flags, parses crash artifacts,
and collects coverage via llvm-profdata / llvm-cov.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import CoverageReport, CrashInfo, FuzzResult

log = logging.getLogger(__name__)


class LibFuzzerEngine:
    """FuzzerEngine implementation for LLVM libFuzzer."""

    name = "libfuzzer"

    def __init__(self, **kwargs: object) -> None:
        pass

    def fuzz(
        self,
        binary: Path,
        corpus_dir: Path,
        **options: object,
    ) -> FuzzResult:
        """Run a libFuzzer binary with the given options.

        Supported options:
            timeout (int): per-testcase timeout in seconds (default 30)
            max_total_time (int): total wall-clock fuzzing time (default 60)
            fork (int): number of fork workers (default 1)
            rss_limit_mb (int): RSS limit in MB (default 2048)
            artifact_prefix (str): directory prefix for crash artifacts
        """
        binary = Path(binary).resolve()
        corpus_dir = Path(corpus_dir).resolve()
        corpus_dir.mkdir(parents=True, exist_ok=True)

        timeout = int(options.get("timeout", 30))  # type: ignore[arg-type]
        max_total_time = int(options.get("max_total_time", 60))  # type: ignore[arg-type]
        fork = int(options.get("fork", 1))  # type: ignore[arg-type]
        rss_limit_mb = int(options.get("rss_limit_mb", 2048))  # type: ignore[arg-type]
        artifact_prefix = str(options.get("artifact_prefix", str(corpus_dir) + "/crash-"))

        cmd = [
            str(binary),
            str(corpus_dir),
            f"-timeout={timeout}",
            f"-max_total_time={max_total_time}",
            f"-rss_limit_mb={rss_limit_mb}",
            f"-artifact_prefix={artifact_prefix}",
        ]
        if fork > 1:
            cmd.append(f"-fork={fork}")

        env = os.environ.copy()
        # Set LLVM profile output for coverage collection
        profraw_path = corpus_dir.parent / "default.profraw"
        env["LLVM_PROFILE_FILE"] = str(profraw_path)

        log.info("Running libFuzzer: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=max_total_time + 30,  # extra margin
            )
        except subprocess.TimeoutExpired:
            log.warning("libFuzzer timed out for %s", binary.name)
            return FuzzResult(
                binary_path=str(binary),
                corpus_dir=str(corpus_dir),
                success=False,
                duration_seconds=float(max_total_time),
            )
        except FileNotFoundError:
            log.warning("Binary not found: %s", binary)
            return FuzzResult(
                binary_path=str(binary),
                corpus_dir=str(corpus_dir),
                success=False,
            )

        # Parse libFuzzer stats from stderr
        duration = _parse_duration(result.stderr)
        execs_per_sec = _parse_execs_per_sec(result.stderr)

        # libFuzzer exit code: 0 = normal exit, 1 = crash found, 77 = OOM
        success = result.returncode in (0, 1)

        return FuzzResult(
            binary_path=str(binary),
            corpus_dir=str(corpus_dir),
            success=success,
            duration_seconds=duration or float(max_total_time),
            execs_per_sec=execs_per_sec,
        )

    def parse_crashes(self, artifact_dir: Path) -> list[CrashInfo]:
        """Parse crash/leak/timeout artifacts from a directory."""
        artifact_dir = Path(artifact_dir)
        if not artifact_dir.is_dir():
            return []

        crashes: list[CrashInfo] = []
        for f in sorted(artifact_dir.iterdir()):
            if not f.is_file():
                continue
            name = f.name.lower()
            if any(name.startswith(prefix) for prefix in ("crash-", "leak-", "timeout-", "oom-")):
                warn_class = name.split("-")[0].upper()
                crashes.append(CrashInfo(
                    artifact_path=str(f),
                    summary=f"{warn_class} artifact: {f.name}",
                    warn_class=warn_class,
                ))

        return crashes

    def get_coverage(self, binary: Path, profdata: Path) -> CoverageReport:
        """Generate coverage report from llvm-profdata merge + llvm-cov export.

        Expects profraw file alongside profdata (same directory, default.profraw).
        """
        binary = Path(binary).resolve()
        profdata = Path(profdata).resolve()
        profraw = profdata.parent / "default.profraw"

        # Merge profraw -> profdata
        if profraw.exists() and not profdata.exists():
            try:
                subprocess.run(
                    ["llvm-profdata", "merge", "-sparse", str(profraw), "-o", str(profdata)],
                    capture_output=True,
                    timeout=60,
                    check=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                log.warning("llvm-profdata merge failed: %s", e)
                return CoverageReport(binary_path=str(binary), profdata_path=str(profdata))

        if not profdata.exists():
            return CoverageReport(binary_path=str(binary), profdata_path=str(profdata))

        # Export coverage summary via llvm-cov
        lines_covered = 0
        lines_total = 0
        regions_covered = 0
        regions_total = 0

        try:
            result = subprocess.run(
                [
                    "llvm-cov", "export", "-summary-only",
                    "-instr-profile", str(profdata),
                    str(binary),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout:
                import json
                data = json.loads(result.stdout)
                totals = data.get("data", [{}])[0].get("totals", {})
                lines = totals.get("lines", {})
                regions = totals.get("regions", {})
                lines_covered = lines.get("covered", 0)
                lines_total = lines.get("count", 0)
                regions_covered = regions.get("covered", 0)
                regions_total = regions.get("count", 0)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning("llvm-cov export failed: %s", e)
        except Exception as e:
            log.warning("Coverage parsing failed: %s", e)

        return CoverageReport(
            binary_path=str(binary),
            profdata_path=str(profdata),
            lines_covered=lines_covered,
            lines_total=lines_total,
            regions_covered=regions_covered,
            regions_total=regions_total,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"Done\s+\d+\s+runs\s+in\s+(\d+)\s+second")
_EXECS_RE = re.compile(r"exec/s:\s+(\d+)")


def _parse_duration(stderr: str) -> float:
    """Extract fuzzing duration from libFuzzer output."""
    m = _DURATION_RE.search(stderr)
    if m:
        return float(m.group(1))
    return 0.0


def _parse_execs_per_sec(stderr: str) -> float:
    """Extract execs/s from libFuzzer output."""
    matches = _EXECS_RE.findall(stderr)
    if matches:
        return float(matches[-1])  # last reported value
    return 0.0


def register(registry: ComponentRegistry) -> None:
    """Register the libFuzzer engine."""
    registry.register_fuzzer("libfuzzer", LibFuzzerEngine)
