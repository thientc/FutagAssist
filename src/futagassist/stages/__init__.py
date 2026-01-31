"""Built-in pipeline stages."""

from futagassist.stages.build_stage import BuildStage


def register_builtin_stages(registry) -> None:
    """Register built-in pipeline stages on the given registry."""
    registry.register_stage("build", BuildStage)


__all__ = [
    "BuildStage",
    "register_builtin_stages",
]
