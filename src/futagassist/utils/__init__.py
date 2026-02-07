"""Shared utilities for pipeline stages."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from futagassist.core.schema import PipelineContext, StageResult

log = logging.getLogger(__name__)


def get_registry_and_config(
    context: PipelineContext,
    stage_name: str,
) -> tuple[Any, Any, StageResult | None]:
    """Extract registry and config_manager from pipeline context.

    Returns:
        (registry, config_manager, None) on success.
        (None, None, StageResult) on failure — caller should return the StageResult.
    """
    registry = context.config.get("registry")
    config_manager = context.config.get("config_manager")
    if not registry or not config_manager:
        return None, None, StageResult(
            stage_name=stage_name,
            success=False,
            message="registry or config_manager not set in context.config",
        )
    return registry, config_manager, None


def get_llm_provider(
    registry: Any,
    config_manager: Any,
    *,
    avail: dict[str, list[str]] | None = None,
) -> Any | None:
    """Try to instantiate the configured LLM provider.

    Returns the LLM provider instance, or None if not available or on error.
    """
    cfg = config_manager.config
    if avail is None:
        avail = registry.list_available()
    try:
        if cfg.llm_provider in avail.get("llm_providers", []):
            return registry.get_llm(cfg.llm_provider, **config_manager.env)
    except Exception:
        pass
    return None


def resolve_output_dir(
    context: PipelineContext,
    config_key: str,
    default_subdir: str,
    *,
    mkdir: bool = True,
    fallback_attr: str | None = None,
) -> Path:
    """Resolve an output directory from context config, repo_path, or cwd.

    Args:
        context: Pipeline context.
        config_key: Key in ``context.config`` that may hold an explicit path.
        default_subdir: Default subdirectory name (e.g. ``"fuzz_targets"``).
        mkdir: If True, create the directory (parents + exist_ok).
        fallback_attr: Optional context attribute to try before repo_path
                       (e.g. ``"results_dir"``).
    """
    explicit = context.config.get(config_key)
    if explicit:
        output = Path(explicit)
    elif fallback_attr and getattr(context, fallback_attr, None):
        output = Path(getattr(context, fallback_attr)) / default_subdir
    elif context.repo_path:
        output = Path(context.repo_path) / default_subdir
    else:
        output = Path.cwd() / default_subdir
    if mkdir:
        output.mkdir(parents=True, exist_ok=True)
    return output
