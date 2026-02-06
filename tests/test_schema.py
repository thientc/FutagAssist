"""Tests for core schema models."""

from __future__ import annotations

from pathlib import Path

from futagassist.core.schema import (
    FunctionInfo,
    GeneratedHarness,
    PipelineContext,
    PipelineResult,
    StageResult,
    UsageContext,
)


def test_pipeline_context_update_merges_data() -> None:
    ctx = PipelineContext()
    ctx.update(
        StageResult(
            stage_name="build",
            success=True,
            data={"db_path": Path("/tmp/codeql-db")},
        )
    )
    assert ctx.db_path == Path("/tmp/codeql-db")
    assert len(ctx.stage_results) == 1


def test_pipeline_context_update_merges_usage_contexts() -> None:
    ctx = PipelineContext()
    uc = UsageContext(name="seq", calls=["a", "b", "c"])
    ctx.update(
        StageResult(
            stage_name="analyze",
            success=True,
            data={"functions": [], "usage_contexts": [uc]},
        )
    )
    assert len(ctx.usage_contexts) == 1
    assert ctx.usage_contexts[0].calls == ["a", "b", "c"]


def test_pipeline_context_finalize() -> None:
    ctx = PipelineContext(language="cpp")
    ctx.update(StageResult(stage_name="s1", success=True))
    ctx.update(StageResult(stage_name="s2", success=False))
    result = ctx.finalize()
    assert result.success is False
    assert len(result.stage_results) == 2
    assert result.stage_results[0].stage_name == "s1"
    assert result.stage_results[1].stage_name == "s2"


def test_function_info_model() -> None:
    f = FunctionInfo(
        name="foo",
        signature="int foo(char *p)",
        return_type="int",
        parameters=["char *p"],
        file_path="src/foo.c",
        line=10,
    )
    assert f.name == "foo"
    assert f.line == 10


def test_usage_context_model() -> None:
    u = UsageContext(
        name="init_use_cleanup",
        calls=["init", "use", "cleanup"],
        source_file="main.c",
        source_line=42,
        description="Typical usage sequence",
    )
    assert u.name == "init_use_cleanup"
    assert u.calls == ["init", "use", "cleanup"]
    assert u.source_line == 42


def test_generated_harness_validation_errors_force_is_valid_false() -> None:
    """When validation_errors is non-empty, is_valid must be False."""
    h = GeneratedHarness(
        function_name="foo",
        validation_errors=["missing include"],
        is_valid=True,  # explicitly set True
    )
    assert h.is_valid is False


def test_generated_harness_no_errors_keeps_is_valid_true() -> None:
    """When validation_errors is empty, is_valid stays True."""
    h = GeneratedHarness(function_name="foo")
    assert h.is_valid is True
    assert h.validation_errors == []


def test_pipeline_context_update_fuzz_install_prefix() -> None:
    """update() merges fuzz_install_prefix from stage result data."""
    ctx = PipelineContext()
    ctx.update(
        StageResult(
            stage_name="fuzz_build",
            success=True,
            data={"fuzz_install_prefix": "/opt/install-fuzz"},
        )
    )
    assert ctx.fuzz_install_prefix == "/opt/install-fuzz"
