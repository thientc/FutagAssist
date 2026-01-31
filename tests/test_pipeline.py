"""Tests for PipelineEngine and PipelineConfig."""

from __future__ import annotations

from pathlib import Path

import pytest

from futagassist.core.exceptions import PipelineError
from futagassist.core.pipeline import PipelineConfig, PipelineEngine
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import PipelineContext, StageResult
from futagassist.protocols import PipelineStage


class _SuccessStage(PipelineStage):
    name = "success_stage"
    depends_on: list[str] = []

    def execute(self, context: PipelineContext) -> StageResult:
        return StageResult(
            stage_name=self.name,
            success=True,
            data={"db_path": Path("/tmp/db")},
        )

    def can_skip(self, context: PipelineContext) -> bool:
        return False


class _FailStage(PipelineStage):
    name = "fail_stage"
    depends_on: list[str] = []

    def execute(self, context: PipelineContext) -> StageResult:
        return StageResult(stage_name=self.name, success=False, message="failed")

    def can_skip(self, context: PipelineContext) -> bool:
        return False


class _RaiseStage(PipelineStage):
    name = "raise_stage"
    depends_on: list[str] = []

    def execute(self, context: PipelineContext) -> StageResult:
        raise ValueError("stage error")

    def can_skip(self, context: PipelineContext) -> bool:
        return False


def test_pipeline_empty_stages() -> None:
    reg = ComponentRegistry()
    config = PipelineConfig(stages=[], skip_stages=[], stop_on_failure=True)
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    result = engine.run(context)
    assert result.success is True
    assert result.stage_results == []


def test_pipeline_skip_stages() -> None:
    reg = ComponentRegistry()
    reg.register_stage("success", _SuccessStage)
    config = PipelineConfig(
        stages=["success"],
        skip_stages=["success"],
        stop_on_failure=True,
    )
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    result = engine.run(context)
    assert result.success is True
    assert len(result.stage_results) == 0


def test_pipeline_run_one_stage() -> None:
    reg = ComponentRegistry()
    reg.register_stage("success", _SuccessStage)
    config = PipelineConfig(stages=["success"], skip_stages=[], stop_on_failure=True)
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    result = engine.run(context)
    assert result.success is True
    assert len(result.stage_results) == 1
    assert result.stage_results[0].stage_name == "success_stage"
    assert result.stage_results[0].success is True
    assert result.db_path == Path("/tmp/db")


def test_pipeline_run_multiple_stages() -> None:
    reg = ComponentRegistry()
    reg.register_stage("s1", _SuccessStage)
    reg.register_stage("s2", _SuccessStage)
    config = PipelineConfig(stages=["s1", "s2"], skip_stages=[], stop_on_failure=True)
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    result = engine.run(context)
    assert result.success is True
    assert len(result.stage_results) == 2


def test_pipeline_stop_on_failure_raises_for_unknown_stage() -> None:
    reg = ComponentRegistry()
    config = PipelineConfig(stages=["nonexistent"], skip_stages=[], stop_on_failure=True)
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    with pytest.raises(PipelineError, match="Failed to get stage"):
        engine.run(context)


def test_pipeline_stop_on_failure_raises_when_stage_raises() -> None:
    reg = ComponentRegistry()
    reg.register_stage("raise", _RaiseStage)
    config = PipelineConfig(stages=["raise"], skip_stages=[], stop_on_failure=True)
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    with pytest.raises(PipelineError, match="Stage raise failed"):
        engine.run(context)


def test_pipeline_no_stop_on_failure_continues_after_unknown_stage() -> None:
    reg = ComponentRegistry()
    reg.register_stage("success", _SuccessStage)
    config = PipelineConfig(
        stages=["nonexistent", "success"],
        skip_stages=[],
        stop_on_failure=False,
    )
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    result = engine.run(context)
    assert len(result.stage_results) == 2
    assert result.stage_results[0].success is False
    assert result.stage_results[1].success is True


def test_pipeline_finalize_reflects_success() -> None:
    reg = ComponentRegistry()
    reg.register_stage("fail", _FailStage)
    config = PipelineConfig(stages=["fail"], skip_stages=[], stop_on_failure=False)
    engine = PipelineEngine(reg, config)
    context = PipelineContext()
    result = engine.run(context)
    assert result.success is False
    assert result.stage_results[0].success is False
