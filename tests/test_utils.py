"""Tests for futagassist.utils — shared utility helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from futagassist.core.schema import PipelineContext, StageResult
from futagassist.utils import get_llm_provider, get_registry_and_config, resolve_output_dir

from _helpers import make_pipeline_context as _make_context


# ===================================================================
# get_registry_and_config
# ===================================================================

class TestGetRegistryAndConfig:
    """Tests for get_registry_and_config()."""

    def test_success(self, mock_registry: MagicMock, mock_config_manager: MagicMock) -> None:
        ctx = _make_context(registry=mock_registry, config_manager=mock_config_manager)
        reg, cfg_mgr, err = get_registry_and_config(ctx, "test-stage")
        assert reg is mock_registry
        assert cfg_mgr is mock_config_manager
        assert err is None

    def test_missing_registry(self, mock_config_manager: MagicMock) -> None:
        ctx = _make_context(config_manager=mock_config_manager)
        reg, cfg_mgr, err = get_registry_and_config(ctx, "build")
        assert reg is None
        assert cfg_mgr is None
        assert isinstance(err, StageResult)
        assert err.success is False
        assert err.stage_name == "build"
        assert "registry or config_manager" in err.message

    def test_missing_config_manager(self, mock_registry: MagicMock) -> None:
        ctx = _make_context(registry=mock_registry)
        _, _, err = get_registry_and_config(ctx, "analyze")
        assert isinstance(err, StageResult)
        assert err.success is False
        assert err.stage_name == "analyze"

    def test_both_missing(self) -> None:
        ctx = _make_context()
        _, _, err = get_registry_and_config(ctx, "report")
        assert isinstance(err, StageResult)
        assert err.success is False

    def test_stage_name_propagated(self, mock_config_manager: MagicMock) -> None:
        """Stage name should appear in the error StageResult."""
        ctx = _make_context(config_manager=mock_config_manager)
        _, _, err = get_registry_and_config(ctx, "my-custom-stage")
        assert err is not None
        assert err.stage_name == "my-custom-stage"


# ===================================================================
# get_llm_provider
# ===================================================================

class TestGetLlmProvider:
    """Tests for get_llm_provider()."""

    def test_success(self, mock_registry: MagicMock, mock_config_manager: MagicMock) -> None:
        llm = get_llm_provider(mock_registry, mock_config_manager)
        assert llm is not None
        mock_registry.get_llm.assert_called_once_with("openai", OPENAI_API_KEY="sk-test")

    def test_success_with_avail(self, mock_registry: MagicMock, mock_config_manager: MagicMock) -> None:
        avail = {"llm_providers": ["openai"]}
        llm = get_llm_provider(mock_registry, mock_config_manager, avail=avail)
        assert llm is not None
        # When avail is passed explicitly, list_available should not be called
        mock_registry.list_available.assert_not_called()

    def test_provider_not_available(self, mock_registry: MagicMock, mock_config_manager: MagicMock) -> None:
        mock_registry.list_available.return_value = {"llm_providers": []}
        llm = get_llm_provider(mock_registry, mock_config_manager)
        assert llm is None
        mock_registry.get_llm.assert_not_called()

    def test_provider_not_in_avail(self, mock_registry: MagicMock, mock_config_manager: MagicMock) -> None:
        avail = {"llm_providers": ["ollama"]}  # config says "openai"
        llm = get_llm_provider(mock_registry, mock_config_manager, avail=avail)
        assert llm is None

    def test_exception_returns_none(self, mock_registry: MagicMock, mock_config_manager: MagicMock) -> None:
        mock_registry.get_llm.side_effect = RuntimeError("API down")
        llm = get_llm_provider(mock_registry, mock_config_manager)
        assert llm is None

    def test_avail_missing_llm_key(self, mock_registry: MagicMock, mock_config_manager: MagicMock) -> None:
        avail: dict = {}  # no "llm_providers" key at all
        llm = get_llm_provider(mock_registry, mock_config_manager, avail=avail)
        assert llm is None


# ===================================================================
# resolve_output_dir
# ===================================================================

class TestResolveOutputDir:
    """Tests for resolve_output_dir()."""

    def test_explicit_config_key(self, tmp_path: Path) -> None:
        explicit = tmp_path / "my-output"
        ctx = _make_context(extra_config={"out": str(explicit)})
        result = resolve_output_dir(ctx, "out", "default_sub")
        assert result == explicit
        assert result.is_dir()

    def test_repo_path_fallback(self, tmp_path: Path) -> None:
        ctx = _make_context(repo_path=tmp_path)
        result = resolve_output_dir(ctx, "nonexistent_key", "fuzz_targets")
        assert result == tmp_path / "fuzz_targets"
        assert result.is_dir()

    def test_cwd_fallback(self) -> None:
        ctx = _make_context()  # no repo_path, no config key
        result = resolve_output_dir(ctx, "nope", "fuzz_binaries", mkdir=False)
        assert result == Path.cwd() / "fuzz_binaries"

    def test_mkdir_false(self, tmp_path: Path) -> None:
        ctx = _make_context(repo_path=tmp_path)
        result = resolve_output_dir(ctx, "missing", "subdir", mkdir=False)
        assert result == tmp_path / "subdir"
        assert not result.exists()

    def test_mkdir_true(self, tmp_path: Path) -> None:
        ctx = _make_context(repo_path=tmp_path)
        result = resolve_output_dir(ctx, "missing", "new_subdir", mkdir=True)
        assert result == tmp_path / "new_subdir"
        assert result.is_dir()

    def test_fallback_attr(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        ctx = _make_context(results_dir=results_dir)
        result = resolve_output_dir(
            ctx, "nope", "reports", fallback_attr="results_dir",
        )
        assert result == results_dir / "reports"
        assert result.is_dir()

    def test_fallback_attr_none_falls_through(self, tmp_path: Path) -> None:
        """When fallback_attr exists but value is None, fall through to repo_path."""
        ctx = _make_context(repo_path=tmp_path)
        result = resolve_output_dir(
            ctx, "nope", "reports", fallback_attr="results_dir",
        )
        assert result == tmp_path / "reports"

    def test_explicit_overrides_fallback(self, tmp_path: Path) -> None:
        """Explicit config key takes priority over fallback_attr and repo_path."""
        explicit = tmp_path / "custom"
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        ctx = _make_context(
            repo_path=tmp_path,
            results_dir=results_dir,
            extra_config={"out": str(explicit)},
        )
        result = resolve_output_dir(
            ctx, "out", "reports", fallback_attr="results_dir",
        )
        assert result == explicit

    def test_nested_subdirs_created(self, tmp_path: Path) -> None:
        ctx = _make_context(repo_path=tmp_path)
        result = resolve_output_dir(ctx, "missing", "a/b/c")
        assert result == tmp_path / "a" / "b" / "c"
        assert result.is_dir()
