"""Tests for FuzzBuildStage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from futagassist.core.schema import PipelineContext
from futagassist.stages.fuzz_build_stage import FuzzBuildStage


def test_fuzz_build_stage_no_repo_path() -> None:
    """When repo_path is None, stage returns failure."""
    stage = FuzzBuildStage()
    ctx = PipelineContext(repo_path=None, config={})
    result = stage.execute(ctx)
    assert result.success is False
    assert "repo_path" in result.message.lower()


def test_fuzz_build_stage_repo_not_dir(tmp_path: Path) -> None:
    """When repo_path is not a directory, stage returns failure."""
    stage = FuzzBuildStage()
    not_dir = tmp_path / "missing"
    ctx = PipelineContext(repo_path=not_dir, config={})
    result = stage.execute(ctx)
    assert result.success is False
    assert "directory" in result.message.lower() or "not" in result.message.lower()


def test_fuzz_build_stage_can_skip_when_prefix_has_lib(tmp_path: Path) -> None:
    """can_skip returns True when fuzz_install_prefix exists and has lib/."""
    (tmp_path / "lib").mkdir(parents=True)
    stage = FuzzBuildStage()
    ctx = PipelineContext(repo_path=tmp_path, fuzz_install_prefix=tmp_path, config={})
    assert stage.can_skip(ctx) is True


def test_fuzz_build_stage_can_skip_when_prefix_has_include(tmp_path: Path) -> None:
    """can_skip returns True when fuzz_install_prefix exists and has include/."""
    (tmp_path / "include").mkdir(parents=True)
    stage = FuzzBuildStage()
    ctx = PipelineContext(repo_path=tmp_path, config={"fuzz_install_prefix": str(tmp_path)})
    assert stage.can_skip(ctx) is True


def test_fuzz_build_stage_can_skip_when_no_prefix(tmp_path: Path) -> None:
    """can_skip returns False when fuzz_install_prefix is None."""
    stage = FuzzBuildStage()
    ctx = PipelineContext(repo_path=tmp_path, config={})
    assert stage.can_skip(ctx) is False


def test_fuzz_build_stage_can_skip_when_prefix_empty_dir(tmp_path: Path) -> None:
    """can_skip returns False when prefix dir exists but has no lib or include."""
    stage = FuzzBuildStage()
    ctx = PipelineContext(repo_path=tmp_path, fuzz_install_prefix=tmp_path, config={})
    assert stage.can_skip(ctx) is False


def test_fuzz_build_stage_execute_success(tmp_path: Path) -> None:
    """Execute with mock subprocess success; result has fuzz_install_prefix and log file."""
    (tmp_path / "README").write_text("make")
    install_fuzz = tmp_path / "install-fuzz"
    install_fuzz.mkdir()
    (install_fuzz / "lib").mkdir()

    with patch("futagassist.stages.fuzz_build_stage.subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ctx = PipelineContext(
            repo_path=tmp_path,
            config={"config_manager": None},
        )
        stage = FuzzBuildStage()
        result = stage.execute(ctx)

    assert result.success is True
    assert result.stage_name == "fuzz_build"
    assert result.data is not None
    assert result.data.get("fuzz_install_prefix") == str(install_fuzz)
    assert "fuzz_build_log_file" in result.data


def test_fuzz_build_stage_execute_failure(tmp_path: Path) -> None:
    """Execute with mock subprocess failure; result has message and log file."""
    (tmp_path / "README").write_text("make")

    with patch("futagassist.stages.fuzz_build_stage.subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 1, "stdout": "err", "stderr": "err"})()
        ctx = PipelineContext(repo_path=tmp_path, config={})
        stage = FuzzBuildStage()
        result = stage.execute(ctx)

    assert result.success is False
    assert "fuzz_install_prefix" not in (result.data or {})
    assert result.data is not None
    assert "fuzz_build_log_file" in result.data


def test_fuzz_build_stage_uses_custom_prefix(tmp_path: Path) -> None:
    """When context has fuzz_install_prefix, that path is used and returned."""
    (tmp_path / "README").write_text("make")
    custom_prefix = tmp_path / "my-fuzz-install"
    custom_prefix.mkdir()
    (custom_prefix / "lib").mkdir()

    with patch("futagassist.stages.fuzz_build_stage.subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ctx = PipelineContext(
            repo_path=tmp_path,
            config={"fuzz_install_prefix": str(custom_prefix)},
        )
        stage = FuzzBuildStage()
        result = stage.execute(ctx)

    assert result.success is True
    assert result.data and result.data.get("fuzz_install_prefix") == str(custom_prefix.resolve())


def test_fuzz_build_stage_log_file_created(tmp_path: Path) -> None:
    """Execute creates log file at default or custom path."""
    (tmp_path / "README").write_text("make")
    log_file = tmp_path / "custom-fuzz-build.log"

    with patch("futagassist.stages.fuzz_build_stage.subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ctx = PipelineContext(
            repo_path=tmp_path,
            config={"fuzz_build_log_file": str(log_file)},
        )
        stage = FuzzBuildStage()
        stage.execute(ctx)

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Fuzz Build" in content or "fuzz_install_prefix" in content
