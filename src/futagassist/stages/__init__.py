"""Built-in pipeline stages."""

from futagassist.stages.analyze_stage import AnalyzeStage
from futagassist.stages.build_stage import BuildStage
from futagassist.stages.compile_stage import CompileStage
from futagassist.stages.fuzz_build_stage import FuzzBuildStage
from futagassist.stages.fuzz_stage import FuzzStage
from futagassist.stages.generate_stage import GenerateStage
from futagassist.stages.report_stage import ReportStage


def register_builtin_stages(registry) -> None:
    """Register built-in pipeline stages on the given registry."""
    registry.register_stage("build", BuildStage)
    registry.register_stage("analyze", AnalyzeStage)
    registry.register_stage("generate", GenerateStage)
    registry.register_stage("fuzz_build", FuzzBuildStage)
    registry.register_stage("compile", CompileStage)
    registry.register_stage("fuzz", FuzzStage)
    registry.register_stage("report", ReportStage)


__all__ = [
    "AnalyzeStage",
    "BuildStage",
    "CompileStage",
    "FuzzBuildStage",
    "FuzzStage",
    "GenerateStage",
    "ReportStage",
    "register_builtin_stages",
]
