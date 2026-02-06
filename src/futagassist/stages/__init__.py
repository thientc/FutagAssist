"""Built-in pipeline stages."""

from futagassist.stages.analyze_stage import AnalyzeStage
from futagassist.stages.build_stage import BuildStage
from futagassist.stages.compile_stage import CompileStage
from futagassist.stages.fuzz_build_stage import FuzzBuildStage
from futagassist.stages.generate_stage import GenerateStage


def register_builtin_stages(registry) -> None:
    """Register built-in pipeline stages on the given registry."""
    registry.register_stage("build", BuildStage)
    registry.register_stage("analyze", AnalyzeStage)
    registry.register_stage("generate", GenerateStage)
    registry.register_stage("fuzz_build", FuzzBuildStage)
    registry.register_stage("compile", CompileStage)


__all__ = [
    "AnalyzeStage",
    "BuildStage",
    "CompileStage",
    "FuzzBuildStage",
    "GenerateStage",
    "register_builtin_stages",
]
