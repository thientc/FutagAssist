"""Fuzz stage: run compiled fuzz targets through a FuzzerEngine and collect results."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from futagassist.utils import get_registry_and_config, resolve_output_dir
from futagassist.core.schema import (
    CoverageReport,
    CrashInfo,
    FuzzResult,
    PipelineContext,
    StageResult,
)

log = logging.getLogger(__name__)


def _deduplicate_crashes(crashes: list[CrashInfo]) -> list[CrashInfo]:
    """Remove duplicate crashes based on (crash_file, crash_line, warn_class).

    When those fields are empty, fall back to a hash of the backtrace.
    """
    seen: set[str] = set()
    unique: list[CrashInfo] = []
    for c in crashes:
        if c.crash_file and c.crash_line:
            key = f"{c.crash_file}:{c.crash_line}:{c.warn_class}"
        elif c.backtrace:
            key = hashlib.md5(c.backtrace.encode("utf-8", errors="replace")).hexdigest()
        elif c.summary:
            key = hashlib.md5(c.summary.encode("utf-8", errors="replace")).hexdigest()
        else:
            key = c.artifact_path or id(c)  # type: ignore[arg-type]
            key = str(key)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


class FuzzStage:
    """Pipeline stage that runs compiled fuzz targets through a FuzzerEngine.

    Features:
    - Delegates execution to a registered ``FuzzerEngine`` plugin
    - Configurable options: ``timeout``, ``max_total_time``, ``fork``, ``rss_limit_mb``
    - Crash log parsing and deduplication
    - Optional coverage collection via ``FuzzerEngine.get_coverage()``
    - Aggregates ``FuzzResult`` objects for every binary
    """

    name = "fuzz"
    depends_on: list[str] = ["compile"]

    def execute(self, context: PipelineContext) -> StageResult:
        """Fuzz each compiled binary and aggregate results."""
        registry, config_manager, err = get_registry_and_config(context, self.name)
        if err:
            return err

        cfg = config_manager.config
        avail = registry.list_available()

        # Resolve fuzzer engine
        engine_name = context.config.get("fuzz_engine") or cfg.fuzzer_engine
        if engine_name not in avail.get("fuzzer_engines", []):
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"Fuzzer engine not registered: {engine_name!r}. Available: {avail.get('fuzzer_engines', [])}",
            )

        try:
            engine = registry.get_fuzzer(engine_name)
        except Exception as e:
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"Failed to instantiate fuzzer engine {engine_name!r}: {e}",
            )

        # Discover binaries
        binaries = self._discover_binaries(context)
        if not binaries:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="No compiled fuzz binaries found (run compile stage first).",
            )

        # Fuzzing options
        max_total_time = context.config.get("fuzz_max_total_time", 60)
        fuzz_timeout = context.config.get("fuzz_timeout", 30)
        fork = context.config.get("fuzz_fork", 1)
        rss_limit_mb = context.config.get("fuzz_rss_limit_mb", 2048)
        collect_coverage = context.config.get("fuzz_coverage", True)

        # Results directory
        results_dir = resolve_output_dir(context, "fuzz_results_dir", "fuzz_results")

        all_results: list[FuzzResult] = []
        all_crashes: list[CrashInfo] = []
        total_execs = 0.0
        total_duration = 0.0

        for binary in binaries:
            binary_name = binary.stem
            corpus_dir = results_dir / binary_name / "corpus"
            corpus_dir.mkdir(parents=True, exist_ok=True)
            artifact_dir = results_dir / binary_name / "artifacts"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            log.info("Fuzzing %s (max_total_time=%ds)", binary_name, max_total_time)

            try:
                fuzz_result = engine.fuzz(
                    binary=binary,
                    corpus_dir=corpus_dir,
                    timeout=fuzz_timeout,
                    max_total_time=max_total_time,
                    fork=fork,
                    rss_limit_mb=rss_limit_mb,
                    artifact_prefix=str(artifact_dir) + "/",
                )
            except Exception as e:
                log.warning("Fuzzer failed for %s: %s", binary_name, e)
                fuzz_result = FuzzResult(
                    binary_path=str(binary),
                    corpus_dir=str(corpus_dir),
                    success=False,
                )

            # Parse crashes from artifact directory
            try:
                crashes = engine.parse_crashes(artifact_dir)
                if crashes:
                    fuzz_result.crashes.extend(crashes)
            except Exception as e:
                log.warning("Crash parsing failed for %s: %s", binary_name, e)

            # Coverage collection
            if collect_coverage:
                profraw = results_dir / binary_name / "default.profraw"
                profdata = results_dir / binary_name / "default.profdata"
                if profraw.exists() or profdata.exists():
                    try:
                        cov = engine.get_coverage(binary, profdata)
                        fuzz_result.coverage = cov
                    except Exception as e:
                        log.warning("Coverage collection failed for %s: %s", binary_name, e)

            all_results.append(fuzz_result)
            all_crashes.extend(fuzz_result.crashes)
            total_execs += fuzz_result.execs_per_sec * fuzz_result.duration_seconds
            total_duration += fuzz_result.duration_seconds

        # Deduplicate crashes across all binaries
        unique_crashes = _deduplicate_crashes(all_crashes)
        log.info(
            "Fuzzing complete: %d binaries, %d total crashes (%d unique), %.0fs total",
            len(binaries), len(all_crashes), len(unique_crashes), total_duration,
        )

        data: dict = {
            "fuzz_results": all_results,
            "results_dir": str(results_dir),
            "binaries_fuzzed": len(binaries),
            "total_crashes": len(all_crashes),
            "unique_crashes": len(unique_crashes),
            "crashes": unique_crashes,
            "total_duration_seconds": total_duration,
        }

        any_success = any(r.success for r in all_results)
        return StageResult(
            stage_name=self.name,
            success=any_success,
            message=(
                f"Fuzzed {len(binaries)} binaries: "
                f"{sum(1 for r in all_results if r.success)} OK, "
                f"{sum(1 for r in all_results if not r.success)} failed, "
                f"{len(unique_crashes)} unique crashes."
            ),
            data=data,
        )

    @staticmethod
    def _discover_binaries(context: PipelineContext) -> list[Path]:
        """Find compiled fuzz binaries from context or filesystem."""
        binaries: list[Path] = []

        # From compile stage results
        for sr in context.stage_results:
            if sr.stage_name == "compile" and sr.data.get("compiled"):
                for item in sr.data["compiled"]:
                    bp = Path(item["binary_path"])
                    if bp.is_file():
                        binaries.append(bp)

        if binaries:
            return sorted(set(binaries))

        # Fallback: scan binaries_dir
        if context.binaries_dir and Path(context.binaries_dir).is_dir():
            for f in sorted(Path(context.binaries_dir).iterdir()):
                if f.is_file() and not f.suffix:
                    binaries.append(f)

        return binaries

    def can_skip(self, context: PipelineContext) -> bool:
        """Can skip if fuzz_results already populated."""
        return len(context.fuzz_results) > 0
