"""Tests for build-stage logging."""

from __future__ import annotations

from pathlib import Path

import pytest

from futagassist.build.build_log import LOGGER_NAME, build_log_context, get_logger


def test_get_logger_returns_logger_with_correct_name() -> None:
    """get_logger returns a logger with futagassist.build name."""
    log = get_logger()
    assert log.name == LOGGER_NAME


def test_build_log_context_creates_log_file(tmp_path: Path) -> None:
    """build_log_context writes to the given log file."""
    log_file = tmp_path / "build.log"
    with build_log_context(log_file, verbose=False) as log:
        log.info("test message")
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test message" in content
    assert "[INFO]" in content or "INFO" in content


def test_build_log_context_removes_handler_on_exit(tmp_path: Path) -> None:
    """build_log_context removes the file handler when exiting (later logs don't go to the file)."""
    log_file = tmp_path / "build.log"
    with build_log_context(log_file, verbose=False) as log:
        log.info("inside context")
    get_logger().info("after context")
    content = log_file.read_text(encoding="utf-8")
    assert "inside context" in content
    assert "after context" not in content


def test_build_log_context_verbose_sets_debug_level(tmp_path: Path) -> None:
    """build_log_context with verbose=True allows DEBUG messages to be written."""
    log_file = tmp_path / "build.log"
    with build_log_context(log_file, verbose=True) as log:
        log.debug("debug message")
    content = log_file.read_text(encoding="utf-8")
    assert "debug message" in content
