"""Pydantic models and data structures for the framework."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class FunctionInfo(BaseModel):
    """Information about a function for fuzz target generation."""

    name: str
    signature: str
    return_type: str = ""
    parameters: list[str] = Field(default_factory=list)
    file_path: str = ""
    line: int = 0
    includes: list[str] = Field(default_factory=list)
    context: str = ""


class UsageContext(BaseModel):
    """Ordered sequence of function calls (usage context) for fuzz target generation."""

    name: str = ""
    calls: list[str] = Field(default_factory=list, description="Function names in call order")
    source_file: str = ""
    source_line: int = 0
    description: str = ""


class CrashInfo(BaseModel):
    """Information about a fuzzer crash."""

    artifact_path: str = ""
    backtrace: str = ""
    summary: str = ""
    warn_class: str = ""
    crash_file: str = ""
    crash_line: int = 0


class CoverageReport(BaseModel):
    """Coverage report from a fuzzing run."""

    binary_path: str = ""
    profdata_path: str = ""
    lines_covered: int = 0
    lines_total: int = 0
    regions_covered: int = 0
    regions_total: int = 0
    html_path: str = ""
    csv_path: str = ""


class FuzzResult(BaseModel):
    """Result of a fuzzing run."""

    binary_path: str = ""
    corpus_dir: str = ""
    crashes: list[CrashInfo] = Field(default_factory=list)
    coverage: CoverageReport | None = None
    duration_seconds: float = 0.0
    execs_per_sec: float = 0.0
    success: bool = True


class PluginInfo(BaseModel):
    """Metadata about a discovered plugin."""

    name: str
    path: Path
    module_name: str
    plugin_type: str = ""


class StageResult(BaseModel):
    """Result produced by a pipeline stage."""

    stage_name: str
    success: bool = True
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class PipelineContext(BaseModel):
    """Mutable context passed between pipeline stages."""

    model_config = {"arbitrary_types_allowed": True}

    repo_path: Path | None = None
    db_path: Path | None = None
    language: str = "cpp"
    functions: list[FunctionInfo] = Field(default_factory=list)
    usage_contexts: list[UsageContext] = Field(default_factory=list)
    fuzz_targets_dir: Path | None = None
    binaries_dir: Path | None = None
    results_dir: Path | None = None
    fuzz_results: list[FuzzResult] = Field(default_factory=list)
    stage_results: list[StageResult] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    def update(self, result: StageResult) -> None:
        """Append a stage result and merge its data into context."""
        self.stage_results.append(result)
        if result.data:
            if "db_path" in result.data:
                self.db_path = result.data["db_path"]
            if "functions" in result.data:
                self.functions = result.data["functions"]
            if "usage_contexts" in result.data:
                self.usage_contexts = result.data["usage_contexts"]
            if "fuzz_targets_dir" in result.data:
                self.fuzz_targets_dir = result.data["fuzz_targets_dir"]
            if "binaries_dir" in result.data:
                self.binaries_dir = result.data["binaries_dir"]
            if "fuzz_results" in result.data:
                self.fuzz_results = result.data["fuzz_results"]

    def finalize(self) -> PipelineResult:
        """Build final pipeline result from context."""
        return PipelineResult(
            success=all(r.success for r in self.stage_results),
            stage_results=self.stage_results,
            db_path=self.db_path,
            functions=self.functions,
            usage_contexts=self.usage_contexts,
            fuzz_targets_dir=self.fuzz_targets_dir,
            binaries_dir=self.binaries_dir,
            fuzz_results=self.fuzz_results,
        )


class PipelineResult(BaseModel):
    """Final result of a pipeline run."""

    model_config = {"arbitrary_types_allowed": True}

    success: bool = True
    stage_results: list[StageResult] = Field(default_factory=list)
    db_path: Path | None = None
    functions: list[FunctionInfo] = Field(default_factory=list)
    usage_contexts: list[UsageContext] = Field(default_factory=list)
    fuzz_targets_dir: Path | None = None
    binaries_dir: Path | None = None
    fuzz_results: list[FuzzResult] = Field(default_factory=list)
