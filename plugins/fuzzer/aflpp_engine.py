"""AFL++ engine plugin for FutagAssist (basic).

Register as "aflpp". Provides a basic AFL++ integration that runs
afl-fuzz on instrumented binaries and parses crash artifacts.

Requires: AFL++ installed and ``afl-fuzz`` on PATH.
Binary must be compiled with ``afl-clang-fast++`` or equivalent.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import CoverageReport, CrashInfo, FuzzResult

log = logging.getLogger(__name__)


class AFLPlusPlusEngine:
    """Basic FuzzerEngine implementation for AFL++."""

    name = "aflpp"

    def __init__(self, **kwargs: object) -> None:
        self._afl_fuzz = str(kwargs.get("afl_fuzz_bin", "afl-fuzz"))

    def fuzz(
        self,
        binary: Path,
        corpus_dir: Path,
        **options: object,
    ) -> FuzzResult:
        """Run afl-fuzz on a binary.

        Supported options:
            timeout (int): per-testcase timeout in ms (afl-fuzz -t, default 1000)
            max_total_time (int): total wall-clock seconds (default 60)
            artifact_prefix (str): output directory (afl-fuzz -o)
        """
        binary = Path(binary).resolve()
        corpus_dir = Path(corpus_dir).resolve()
        corpus_dir.mkdir(parents=True, exist_ok=True)

        timeout_ms = int(options.get("timeout", 1000))  # type: ignore[arg-type]
        max_total_time = int(options.get("max_total_time", 60))  # type: ignore[arg-type]
        output_dir = str(options.get("artifact_prefix", str(corpus_dir.parent / "afl_output")))
        output_path = Path(output_dir.rstrip("/"))
        output_path.mkdir(parents=True, exist_ok=True)

        # Ensure there is at least one seed in corpus
        if not any(corpus_dir.iterdir()):
            seed = corpus_dir / "seed_0"
            seed.write_bytes(b"AAAA")

        cmd = [
            self._afl_fuzz,
            "-i", str(corpus_dir),
            "-o", str(output_path),
            "-t", str(timeout_ms),
            "-V", str(max_total_time),  # -V = max total time
            "--", str(binary),
        ]

        env = os.environ.copy()
        env["AFL_NO_UI"] = "1"  # headless
        env.setdefault("AFL_SKIP_CPUFREQ", "1")

        log.info("Running AFL++: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=max_total_time + 60,
            )
        except subprocess.TimeoutExpired:
            log.warning("AFL++ timed out for %s", binary.name)
            return FuzzResult(
                binary_path=str(binary),
                corpus_dir=str(corpus_dir),
                success=False,
                duration_seconds=float(max_total_time),
            )
        except FileNotFoundError:
            log.warning("afl-fuzz not found: %s", self._afl_fuzz)
            return FuzzResult(
                binary_path=str(binary),
                corpus_dir=str(corpus_dir),
                success=False,
            )

        return FuzzResult(
            binary_path=str(binary),
            corpus_dir=str(corpus_dir),
            success=result.returncode == 0,
            duration_seconds=float(max_total_time),
        )

    def parse_crashes(self, artifact_dir: Path) -> list[CrashInfo]:
        """Parse crash files from AFL++ output directory.

        AFL++ stores crashes in ``<output>/default/crashes/``.
        """
        crashes: list[CrashInfo] = []
        artifact_dir = Path(artifact_dir)

        # Check both direct files and AFL++ default layout
        crash_dirs = [artifact_dir]
        for sub in ("default/crashes", "crashes"):
            candidate = artifact_dir / sub
            if candidate.is_dir():
                crash_dirs.append(candidate)

        for d in crash_dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file() or f.name == "README.txt":
                    continue
                if f.name.startswith("id:") or f.name.startswith("crash-"):
                    crashes.append(CrashInfo(
                        artifact_path=str(f),
                        summary=f"AFL++ crash: {f.name}",
                        warn_class="CRASH",
                    ))

        return crashes

    def get_coverage(self, binary: Path, profdata: Path) -> CoverageReport:
        """AFL++ does not produce llvm profdata by default; return empty report."""
        return CoverageReport(
            binary_path=str(binary),
            profdata_path=str(profdata),
        )


def register(registry: ComponentRegistry) -> None:
    """Register the AFL++ engine."""
    registry.register_fuzzer("aflpp", AFLPlusPlusEngine)
