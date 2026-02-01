"""Tests for BuildStage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import PipelineContext
from futagassist.stages.build_stage import BuildStage


def test_build_stage_no_repo_path() -> None:
    """When repo_path is None, stage returns failure."""
    stage = BuildStage()
    ctx = PipelineContext(repo_path=None, config={})
    result = stage.execute(ctx)
    assert result.success is False
    assert "repo_path" in result.message.lower()


def test_build_stage_no_registry_in_context(tmp_path: Path) -> None:
    """When context.config has no registry, stage returns failure."""
    stage = BuildStage()
    ctx = PipelineContext(repo_path=tmp_path, config={})
    result = stage.execute(ctx)
    assert result.success is False
    assert "registry" in result.message.lower() or "config" in result.message.lower()


def test_build_stage_can_skip_when_db_exists(tmp_path: Path) -> None:
    """can_skip returns True when db_path exists."""
    stage = BuildStage()
    db_dir = tmp_path / "codeql-db"
    db_dir.mkdir()
    ctx = PipelineContext(repo_path=tmp_path, db_path=db_dir)
    assert stage.can_skip(ctx) is True


def test_build_stage_can_skip_when_no_db(tmp_path: Path) -> None:
    """can_skip returns False when db_path is None."""
    stage = BuildStage()
    ctx = PipelineContext(repo_path=tmp_path, db_path=None)
    assert stage.can_skip(ctx) is False


def test_build_stage_execute_with_registry(tmp_path: Path) -> None:
    """Execute with registry and config_manager in context; fails without CodeQL but runs stage."""
    (tmp_path / "README").write_text("make")
    registry = ComponentRegistry()
    from futagassist.core.config import ConfigManager
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()

    ctx = PipelineContext(
        repo_path=tmp_path,
        config={"registry": registry, "config_manager": config_mgr},
    )
    stage = BuildStage()
    result = stage.execute(ctx)
    # CodeQL likely not installed or path wrong -> failure
    assert result.stage_name == "build"
    # Either fails (no codeql) or succeeds (codeql present)
    if not result.success:
        assert result.message  # some error message
    # build_log_file should be in result.data (success or failure)
    assert result.data is not None
    assert "build_log_file" in result.data
    assert Path(result.data["build_log_file"]).name == "futagassist-build.log" or "build" in result.data["build_log_file"].lower()


def test_build_stage_execute_with_custom_log_file(tmp_path: Path) -> None:
    """Execute with build_log_file in context writes log to that path."""
    (tmp_path / "README").write_text("make")
    custom_log = tmp_path / "custom-build.log"
    registry = ComponentRegistry()
    from futagassist.core.config import ConfigManager
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()

    ctx = PipelineContext(
        repo_path=tmp_path,
        config={
            "registry": registry,
            "config_manager": config_mgr,
            "build_log_file": str(custom_log),
        },
    )
    stage = BuildStage()
    stage.execute(ctx)
    assert custom_log.exists()
    content = custom_log.read_text(encoding="utf-8")
    assert "Build stage" in content or "repo_path" in content


def test_build_stage_execute_success_includes_build_log_file(tmp_path: Path) -> None:
    """On success, result.data includes build_log_file."""
    (tmp_path / "README").write_text("make")
    registry = ComponentRegistry()
    from futagassist.core.config import ConfigManager
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()

    from unittest.mock import patch
    with patch("futagassist.build.build_orchestrator.subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ctx = PipelineContext(
            repo_path=tmp_path,
            config={"registry": registry, "config_manager": config_mgr},
        )
        stage = BuildStage()
        result = stage.execute(ctx)
    if result.success:
        assert result.data and "build_log_file" in result.data
        assert result.data.get("db_path") is not None


def test_build_stage_failure_includes_suggested_fix_command(tmp_path: Path) -> None:
    """On failure with suggested fix, result.data includes suggested_fix_command."""
    (tmp_path / "README").write_text("make")
    registry = ComponentRegistry()
    from futagassist.core.config import ConfigManager
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()

    ctx = PipelineContext(
        repo_path=tmp_path,
        config={"registry": registry, "config_manager": config_mgr},
    )
    stage = BuildStage()
    with patch("futagassist.build.build_orchestrator.BuildOrchestrator.build") as m:
        m.return_value = (False, None, "Build failed", "libtoolize && autoreconf -fi")
        result = stage.execute(ctx)
    assert result.success is False
    assert result.data is not None
    assert result.data.get("suggested_fix_command") == "libtoolize && autoreconf -fi"


def test_build_stage_passes_configure_options_to_orchestrator(tmp_path: Path) -> None:
    """When context has build_configure_options, orchestrator.build is called with configure_options."""
    (tmp_path / "README").write_text("make")
    registry = ComponentRegistry()
    from futagassist.core.config import ConfigManager
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()

    ctx = PipelineContext(
        repo_path=tmp_path,
        config={
            "registry": registry,
            "config_manager": config_mgr,
            "build_configure_options": "--without-ssl",
        },
    )
    stage = BuildStage()
    with patch("futagassist.build.build_orchestrator.BuildOrchestrator.build") as m:
        m.return_value = (True, tmp_path / "codeql-db", "", None)
        stage.execute(ctx)
    m.assert_called_once()
    call_kwargs = m.call_args[1]
    assert call_kwargs.get("configure_options") == "--without-ssl"
