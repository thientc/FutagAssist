"""Framework core: registry, pipeline, plugin loader, schema."""

from futagassist.core.pipeline import PipelineConfig, PipelineEngine
from futagassist.core.plugin_loader import PluginLoader
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import (
    CrashInfo,
    CoverageReport,
    FunctionInfo,
    FuzzResult,
    PipelineContext,
    PipelineResult,
    PluginInfo,
    StageResult,
)

__all__ = [
    "ComponentRegistry",
    "CrashInfo",
    "CoverageReport",
    "FunctionInfo",
    "FuzzResult",
    "PipelineConfig",
    "PipelineContext",
    "PipelineEngine",
    "PipelineResult",
    "PluginInfo",
    "PluginLoader",
    "StageResult",
]
