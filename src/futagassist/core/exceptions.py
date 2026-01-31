"""Custom exception hierarchy for FutagAssist."""

from __future__ import annotations


class FutagAssistError(Exception):
    """Base exception for FutagAssist."""

    pass


class RegistryError(FutagAssistError):
    """Raised when a component is not found or registration fails."""

    pass


class PluginLoadError(FutagAssistError):
    """Raised when a plugin fails to load."""

    pass


class PipelineError(FutagAssistError):
    """Raised when a pipeline stage fails."""

    pass
