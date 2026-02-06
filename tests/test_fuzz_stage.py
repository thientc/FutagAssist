"""Tests for FuzzStage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from futagassist.core.config import ConfigManager
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import (
    CoverageReport,
    CrashInfo,
    FuzzResult,
    PipelineContext,
    StageResult,
)
from futagassist.stages.fuzz_stage import FuzzStage, _deduplicate_crashes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_manager(tmp_path: Path) -> ConfigManager:
    mgr = ConfigManager(project_root=tmp_path)
    mgr._config_path = tmp_path / "nonexistent.yaml"
    mgr._env_path = tmp_path / ".env"
    mgr.load()
    return mgr


class _MockFuzzerEngine:
    """Minimal FuzzerEngine implementation for tests."""

    name = "mock"

    def __init__(self, **kwargs) -> None:
        self._fuzz_result: FuzzResult | None = None
        self._crashes: list[CrashInfo] = []
        self._coverage: CoverageReport | None = None

    def fuzz(self, binary: Path, corpus_dir: Path, **options) -> FuzzResult:
        if self._fuzz_result is not None:
            return self._fuzz_result
        return FuzzResult(
            binary_path=str(binary),
            corpus_dir=str(corpus_dir),
            success=True,
            duration_seconds=10.0,
            execs_per_sec=100.0,
        )

    def parse_crashes(self, artifact_dir: Path) -> list[CrashInfo]:
        return self._crashes

    def get_coverage(self, binary: Path, profdata: Path) -> CoverageReport:
        if self._coverage:
            return self._coverage
        return CoverageReport(binary_path=str(binary), profdata_path=str(profdata))


def _make_registry_with_engine() -> ComponentRegistry:
    registry = ComponentRegistry()
    from futagassist.stages import register_builtin_stages
    register_builtin_stages(registry)
    registry.register_fuzzer("mock", _MockFuzzerEngine)
    return registry


def _make_context(
    tmp_path: Path,
    with_engine: bool = True,
    binaries: list[str] | None = None,
    extra_config: dict | None = None,
) -> PipelineContext:
    if with_engine:
        registry = _make_registry_with_engine()
    else:
        registry = ComponentRegistry()
        from futagassist.stages import register_builtin_stages
        register_builtin_stages(registry)

    config_mgr = _make_config_manager(tmp_path)
    config_mgr._config.fuzzer_engine = "mock"

    # Create binary files
    binaries_dir = tmp_path / "fuzz_binaries"
    binaries_dir.mkdir(exist_ok=True)
    if binaries:
        for name in binaries:
            (binaries_dir / name).write_bytes(b"\x7fELF")

    config = {
        "registry": registry,
        "config_manager": config_mgr,
        "fuzz_engine": "mock",
        **(extra_config or {}),
    }

    return PipelineContext(
        repo_path=tmp_path,
        binaries_dir=binaries_dir,
        config=config,
    )


# ---------------------------------------------------------------------------
# Unit tests: _deduplicate_crashes
# ---------------------------------------------------------------------------


class TestDeduplicateCrashes:
    def test_no_crashes(self) -> None:
        assert _deduplicate_crashes([]) == []

    def test_unique_crashes_preserved(self) -> None:
        crashes = [
            CrashInfo(crash_file="a.c", crash_line=1, warn_class="ASAN"),
            CrashInfo(crash_file="b.c", crash_line=2, warn_class="UBSAN"),
        ]
        result = _deduplicate_crashes(crashes)
        assert len(result) == 2

    def test_duplicate_location_deduped(self) -> None:
        crashes = [
            CrashInfo(crash_file="a.c", crash_line=10, warn_class="ASAN"),
            CrashInfo(crash_file="a.c", crash_line=10, warn_class="ASAN"),
            CrashInfo(crash_file="a.c", crash_line=10, warn_class="ASAN"),
        ]
        result = _deduplicate_crashes(crashes)
        assert len(result) == 1

    def test_dedup_by_backtrace(self) -> None:
        crashes = [
            CrashInfo(backtrace="frame1\nframe2"),
            CrashInfo(backtrace="frame1\nframe2"),
            CrashInfo(backtrace="frame3\nframe4"),
        ]
        result = _deduplicate_crashes(crashes)
        assert len(result) == 2

    def test_dedup_by_summary(self) -> None:
        crashes = [
            CrashInfo(summary="heap-buffer-overflow in foo"),
            CrashInfo(summary="heap-buffer-overflow in foo"),
        ]
        result = _deduplicate_crashes(crashes)
        assert len(result) == 1

    def test_dedup_mixed_keys(self) -> None:
        crashes = [
            CrashInfo(crash_file="a.c", crash_line=1, warn_class="X"),
            CrashInfo(backtrace="bt1"),
            CrashInfo(summary="sum1"),
            CrashInfo(crash_file="a.c", crash_line=1, warn_class="X"),  # dup
            CrashInfo(backtrace="bt1"),  # dup
        ]
        result = _deduplicate_crashes(crashes)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# FuzzStage: validation
# ---------------------------------------------------------------------------


class TestFuzzStageValidation:
    def test_no_registry(self, tmp_path: Path) -> None:
        ctx = PipelineContext(repo_path=tmp_path, config={})
        stage = FuzzStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "registry" in result.message.lower()

    def test_no_fuzzer_engine(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, with_engine=False, extra_config={"fuzz_engine": "nonexistent"})
        stage = FuzzStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "not registered" in result.message.lower() or "nonexistent" in result.message

    def test_no_binaries(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, binaries=[])
        stage = FuzzStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "No compiled fuzz binaries" in result.message


# ---------------------------------------------------------------------------
# FuzzStage: execution
# ---------------------------------------------------------------------------


class TestFuzzStageExecution:
    def test_fuzz_single_binary(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, binaries=["fuzz_foo"])
        stage = FuzzStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert result.data["binaries_fuzzed"] == 1
        assert len(result.data["fuzz_results"]) == 1
        assert "results_dir" in result.data

    def test_fuzz_multiple_binaries(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, binaries=["fuzz_a", "fuzz_b", "fuzz_c"])
        stage = FuzzStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert result.data["binaries_fuzzed"] == 3

    def test_fuzz_creates_corpus_and_artifact_dirs(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, binaries=["fuzz_test"])
        stage = FuzzStage()
        result = stage.execute(ctx)

        assert result.success is True
        results_dir = Path(result.data["results_dir"])
        assert (results_dir / "fuzz_test" / "corpus").is_dir()
        assert (results_dir / "fuzz_test" / "artifacts").is_dir()

    def test_fuzz_with_crashes(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, binaries=["fuzz_foo"])
        stage = FuzzStage()

        # Patch engine to return crashes
        registry = ctx.config["registry"]
        engine_cls = registry._fuzzer_engines["mock"]
        original_parse = engine_cls.parse_crashes

        def mock_parse(self, artifact_dir):
            return [
                CrashInfo(crash_file="foo.c", crash_line=42, warn_class="ASAN", summary="heap-buffer-overflow"),
            ]

        engine_cls.parse_crashes = mock_parse
        try:
            result = stage.execute(ctx)
        finally:
            engine_cls.parse_crashes = original_parse

        assert result.success is True
        assert result.data["total_crashes"] == 1
        assert result.data["unique_crashes"] == 1

    def test_fuzz_engine_exception_graceful(self, tmp_path: Path) -> None:
        """When FuzzerEngine.fuzz() raises, result is marked as failed but stage continues."""
        ctx = _make_context(tmp_path, binaries=["fuzz_boom"])
        stage = FuzzStage()

        registry = ctx.config["registry"]
        engine_cls = registry._fuzzer_engines["mock"]
        original_fuzz = engine_cls.fuzz

        def boom_fuzz(self, binary, corpus_dir, **options):
            raise RuntimeError("engine crashed")

        engine_cls.fuzz = boom_fuzz
        try:
            result = stage.execute(ctx)
        finally:
            engine_cls.fuzz = original_fuzz

        # Stage returns a result (success=False for the binary, but stage still completes)
        assert result.data["binaries_fuzzed"] == 1

    def test_fuzz_custom_results_dir(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "my_results"
        ctx = _make_context(
            tmp_path,
            binaries=["fuzz_foo"],
            extra_config={"fuzz_results_dir": str(custom_dir)},
        )
        stage = FuzzStage()
        result = stage.execute(ctx)

        assert result.success is True
        assert result.data["results_dir"] == str(custom_dir)
        assert custom_dir.is_dir()


# ---------------------------------------------------------------------------
# FuzzStage: binary discovery
# ---------------------------------------------------------------------------


class TestFuzzStageBinaryDiscovery:
    def test_discover_from_binaries_dir(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, binaries=["fuzz_a", "fuzz_b"])
        stage = FuzzStage()
        binaries = stage._discover_binaries(ctx)
        assert len(binaries) == 2

    def test_discover_from_compile_stage_results(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bins"
        bin_dir.mkdir()
        (bin_dir / "fuzz_x").write_bytes(b"\x7fELF")
        (bin_dir / "fuzz_y").write_bytes(b"\x7fELF")

        ctx = PipelineContext(
            repo_path=tmp_path,
            stage_results=[
                StageResult(
                    stage_name="compile",
                    success=True,
                    data={
                        "compiled": [
                            {"binary_path": str(bin_dir / "fuzz_x"), "function_name": "x"},
                            {"binary_path": str(bin_dir / "fuzz_y"), "function_name": "y"},
                        ],
                    },
                ),
            ],
        )
        stage = FuzzStage()
        binaries = stage._discover_binaries(ctx)
        assert len(binaries) == 2

    def test_discover_ignores_files_with_extension(self, tmp_path: Path) -> None:
        binaries_dir = tmp_path / "fuzz_binaries"
        binaries_dir.mkdir()
        (binaries_dir / "fuzz_a").write_bytes(b"\x7fELF")
        (binaries_dir / "fuzz_a.cpp").write_text("source")
        (binaries_dir / "fuzz_a.o").write_bytes(b"\x00")

        ctx = PipelineContext(repo_path=tmp_path, binaries_dir=binaries_dir)
        stage = FuzzStage()
        binaries = stage._discover_binaries(ctx)
        assert len(binaries) == 1
        assert binaries[0].name == "fuzz_a"

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        binaries_dir = tmp_path / "empty"
        binaries_dir.mkdir()
        ctx = PipelineContext(repo_path=tmp_path, binaries_dir=binaries_dir)
        stage = FuzzStage()
        assert stage._discover_binaries(ctx) == []


# ---------------------------------------------------------------------------
# FuzzStage: can_skip
# ---------------------------------------------------------------------------


class TestFuzzStageCanSkip:
    def test_can_skip_with_results(self) -> None:
        ctx = PipelineContext(fuzz_results=[FuzzResult(success=True)])
        stage = FuzzStage()
        assert stage.can_skip(ctx) is True

    def test_cannot_skip_no_results(self) -> None:
        ctx = PipelineContext()
        stage = FuzzStage()
        assert stage.can_skip(ctx) is False


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestFuzzCLI:
    def test_cli_fuzz_help(self) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["fuzz", "--help"])
        assert result.exit_code == 0
        assert "--binaries" in result.output
        assert "--engine" in result.output
        assert "--max-time" in result.output
        assert "--fork" in result.output
        assert "--no-coverage" in result.output

    def test_cli_fuzz_no_binaries(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        runner = CliRunner()
        result = runner.invoke(main, ["fuzz", "--binaries", str(empty_dir)])
        assert result.exit_code != 0
        assert "No fuzz binaries" in result.output
