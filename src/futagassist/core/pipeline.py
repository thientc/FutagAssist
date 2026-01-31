"""Pipeline engine with stage skip/include support."""

from __future__ import annotations

from dataclasses import dataclass

from futagassist.core.exceptions import PipelineError
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import PipelineContext, PipelineResult, StageResult


@dataclass
class PipelineConfig:
    """Configuration for pipeline execution."""

    stages: list[str]
    skip_stages: list[str]
    stop_on_failure: bool = True


class PipelineEngine:
    """Executes pipeline stages with skip/include support."""

    def __init__(
        self,
        registry: ComponentRegistry,
        config: PipelineConfig,
    ) -> None:
        self._registry = registry
        self._config = config

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def registry(self) -> ComponentRegistry:
        return self._registry

    def run(self, context: PipelineContext) -> PipelineResult:
        """Run all non-skipped stages and return the final result."""
        for stage_name in self._config.stages:
            if stage_name in self._config.skip_stages:
                continue
            try:
                stage = self._registry.get_stage(stage_name)
            except Exception as e:
                if self._config.stop_on_failure:
                    raise PipelineError(f"Failed to get stage {stage_name}: {e}") from e
                context.stage_results.append(
                    StageResult(
                        stage_name=stage_name,
                        success=False,
                        message=str(e),
                    )
                )
                continue

            if getattr(stage, "can_skip", None) and stage.can_skip(context):
                continue

            try:
                result = stage.execute(context)
            except Exception as e:
                if self._config.stop_on_failure:
                    raise PipelineError(f"Stage {stage_name} failed: {e}") from e
                result = StageResult(
                    stage_name=stage_name,
                    success=False,
                    message=str(e),
                )

            context.update(result)
            if self._config.stop_on_failure and not result.success:
                break

        return context.finalize()
