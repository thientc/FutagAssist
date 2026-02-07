"""Shared test helpers and factory functions for FutagAssist tests.

Import this module directly from test files::

    from _helpers import make_config_manager, make_pipeline_context

Pytest fixtures that wrap these factories live in ``conftest.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from futagassist.core.config import ConfigManager
from futagassist.core.schema import (
    CoverageReport,
    CrashInfo,
    FunctionInfo,
    GeneratedHarness,
    PipelineContext,
)


# ---------------------------------------------------------------------------
# ConfigManager factory
# ---------------------------------------------------------------------------


def make_config_manager(tmp_path: Path) -> ConfigManager:
    """Create a real ConfigManager pointed at a nonexistent config/env so defaults are used."""
    mgr = ConfigManager(project_root=tmp_path)
    mgr._config_path = tmp_path / "nonexistent.yaml"
    mgr._env_path = tmp_path / ".env"
    mgr.load()
    return mgr


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def make_mock_registry() -> MagicMock:
    """Return a MagicMock registry with sensible ``list_available`` defaults."""
    reg = MagicMock()
    reg.list_available.return_value = {
        "llm_providers": ["openai"],
        "fuzzer_engines": ["libfuzzer"],
        "language_analyzers": ["cpp"],
        "reporters": ["json", "sarif", "html"],
        "stages": [],
    }
    reg.get_llm.return_value = MagicMock(name="openai-llm-instance")
    return reg


def make_mock_config_manager() -> MagicMock:
    """Return a MagicMock config_manager whose ``.config`` mirrors :class:`AppConfig` defaults."""
    cfg_mgr = MagicMock()
    cfg_mgr.config = SimpleNamespace(
        llm_provider="openai",
        language="cpp",
        codeql_home=None,
        llm=SimpleNamespace(max_retries=3),
        fuzzer_engine="libfuzzer",
    )
    cfg_mgr.env = {"OPENAI_API_KEY": "sk-test"}
    return cfg_mgr


# ---------------------------------------------------------------------------
# PipelineContext factory
# ---------------------------------------------------------------------------


def make_pipeline_context(
    *,
    repo_path: Path | None = None,
    registry: Any = None,
    config_manager: Any = None,
    results_dir: Path | None = None,
    extra_config: dict | None = None,
    **kwargs: Any,
) -> PipelineContext:
    """Build a :class:`PipelineContext` with registry/config_manager wired into ``config``.

    Extra keyword arguments are forwarded to the PipelineContext constructor
    (e.g. ``functions``, ``generated_harnesses``, ``binaries_dir``).
    """
    config: dict = {}
    if registry is not None:
        config["registry"] = registry
    if config_manager is not None:
        config["config_manager"] = config_manager
    if extra_config:
        config.update(extra_config)
    return PipelineContext(
        repo_path=repo_path,
        results_dir=results_dir,
        config=config,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def make_sample_functions() -> list[FunctionInfo]:
    """Return a small list of representative :class:`FunctionInfo` instances."""
    return [
        FunctionInfo(
            name="parse_data",
            signature="int parse_data(const char* data, size_t size)",
            return_type="int",
            parameters=["const char* data", "size_t size"],
            file_path="parser.c",
            line=42,
            is_api=True,
        ),
        FunctionInfo(
            name="process_buffer",
            signature="void process_buffer(uint8_t* buf, int len)",
            return_type="void",
            parameters=["uint8_t* buf", "int len"],
            file_path="processor.c",
            line=100,
            is_fuzz_target_candidate=True,
        ),
    ]


def make_sample_harness(
    name: str = "foo",
    valid: bool = True,
    source: str = "",
) -> GeneratedHarness:
    """Create a :class:`GeneratedHarness` with minimal valid source code."""
    code = source or (
        '#include <stdint.h>\n'
        'extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {\n'
        '    return 0;\n'
        '}\n'
    )
    return GeneratedHarness(
        function_name=name,
        file_path=f"fuzz_targets/harness_{name}.cpp",
        source_code=code,
        is_valid=valid,
    )


def make_sample_crashes() -> list[CrashInfo]:
    """Return a small list of representative :class:`CrashInfo` instances."""
    return [
        CrashInfo(
            crash_file="src/foo.c",
            crash_line=42,
            warn_class="ASAN",
            summary="heap-buffer-overflow",
        ),
        CrashInfo(
            artifact_path="/tmp/crash-abc",
            warn_class="CRASH",
            summary="unknown crash",
        ),
    ]


def make_sample_coverage() -> CoverageReport:
    """Return a representative :class:`CoverageReport`."""
    return CoverageReport(
        binary_path="/bin/fuzz_foo",
        profdata_path="/tmp/default.profdata",
        lines_covered=50,
        lines_total=100,
        regions_covered=30,
        regions_total=60,
    )
