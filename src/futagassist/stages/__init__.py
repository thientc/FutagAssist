"""Built-in pipeline stages."""

from futagassist.stages.analyze_stage import AnalyzeStage
from futagassist.stages.build_stage import BuildStage


def register_builtin_stages(registry) -> None:
    """Register built-in pipeline stages on the given registry."""
    registry.register_stage("build", BuildStage)
    registry.register_stage("analyze", AnalyzeStage)


__all__ = [
    "AnalyzeStage",
    "BuildStage",
    "register_builtin_stages",
]
