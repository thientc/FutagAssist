"""Framework core: registry, pipeline, plugin loader, schema, config, health."""

from futagassist.core.config import ConfigManager
from futagassist.core.health import HealthChecker, HealthCheckResult
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
    UsageContext,
)

__all__ = [
    "ComponentRegistry",
    "ConfigManager",
    "CrashInfo",
    "CoverageReport",
    "FunctionInfo",
    "FuzzResult",
    "HealthCheckResult",
    "HealthChecker",
    "PipelineConfig",
    "PipelineContext",
    "PipelineEngine",
    "PipelineResult",
    "PluginInfo",
    "PluginLoader",
    "StageResult",
    "UsageContext",
]
