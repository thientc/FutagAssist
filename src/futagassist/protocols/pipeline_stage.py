"""Protocol for pipeline stages."""

from __future__ import annotations

from typing import Protocol

from futagassist.core.schema import PipelineContext, StageResult


class PipelineStage(Protocol):
    """Protocol for pipeline stages.

    Attributes:
        name: Unique identifier for this stage.
        depends_on: Stages that must run before this one.  Currently used for
            documentation only -- the pipeline engine executes stages in the
            order given by ``config.stages`` and does **not** perform automatic
            topological sorting.  Implementations should still declare their
            dependencies so that future engine versions (or external tooling)
            can validate ordering.
    """

    name: str
    depends_on: list[str]

    def execute(self, context: PipelineContext) -> StageResult:
        """Run the stage and return a result."""
        ...

    def can_skip(self, context: PipelineContext) -> bool:
        """Return True if this stage can be skipped given the context."""
        ...
