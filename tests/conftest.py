"""Shared pytest fixtures for FutagAssist tests.

Factory functions live in ``_helpers.py``; this module re-exports them as
pytest fixtures so tests can receive them via dependency injection.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from futagassist.core.config import ConfigManager
from futagassist.core.schema import FunctionInfo

from _helpers import (  # noqa: F401 — re-export for fixture use
    make_config_manager,
    make_mock_config_manager,
    make_mock_registry,
    make_pipeline_context,
    make_sample_crashes,
    make_sample_coverage,
    make_sample_functions,
    make_sample_harness,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_manager(tmp_path: Path) -> ConfigManager:
    """A real ConfigManager backed by default config (no YAML/env file)."""
    return make_config_manager(tmp_path)


@pytest.fixture()
def mock_registry() -> MagicMock:
    """A MagicMock registry with sensible ``list_available`` defaults."""
    return make_mock_registry()


@pytest.fixture()
def mock_config_manager() -> MagicMock:
    """A MagicMock config_manager whose ``.config`` mirrors AppConfig defaults."""
    return make_mock_config_manager()


@pytest.fixture()
def sample_functions() -> list[FunctionInfo]:
    """A small list of representative FunctionInfo instances."""
    return make_sample_functions()
