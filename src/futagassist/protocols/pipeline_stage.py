"""Protocol for pipeline stages."""

from __future__ import annotations

from typing import Protocol

from futagassist.core.schema import PipelineContext, StageResult


class PipelineStage(Protocol):
    """Protocol for pipeline stages."""

    name: str
    depends_on: list[str]

    def execute(self, context: PipelineContext) -> StageResult:
        """Run the stage and return a result."""
        ...

    def can_skip(self, context: PipelineContext) -> bool:
        """Return True if this stage can be skipped given the context."""
        ...
