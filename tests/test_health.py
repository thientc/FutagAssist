"""Tests for HealthChecker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from futagassist.core.config import ConfigManager
from futagassist.core.health import HealthChecker, HealthCheckResult
from futagassist.core.registry import ComponentRegistry
from tests.test_registry import _MockLLM


def test_health_check_result() -> None:
    r = HealthCheckResult(name="x", ok=True, message="ok")
    assert r.name == "x"
    assert r.ok is True
    assert r.message == "ok"


def test_health_checker_check_codeql_found() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    with patch("subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "2.15.0", "stderr": ""})()
        result = checker.check_codeql()
    assert result.name == "codeql"
    assert result.ok is True


def test_health_checker_check_codeql_not_found() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    with patch("subprocess.run") as m:
        m.side_effect = FileNotFoundError()
        result = checker.check_codeql()
    assert result.name == "codeql"
    assert result.ok is False
    assert "not found" in result.message or "command" in result.message.lower()


def test_health_checker_check_llm_no_provider_registered() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    result = checker.check_llm()
    assert result.name == "llm"
    assert result.ok is False
    assert "openai" in result.message or "registered" in result.message.lower()


def test_health_checker_check_llm_provider_ok() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    registry.register_llm("openai", _MockLLM)
    checker = HealthChecker(config=config, registry=registry)
    result = checker.check_llm()
    assert result.name == "llm"
    assert result.ok is True
    assert "openai" in result.message


def test_health_checker_check_fuzzer_not_registered() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    result = checker.check_fuzzer()
    assert result.name == "fuzzer"
    assert result.ok is False


def test_health_checker_check_all_skip_llm() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    results = checker.check_all(skip_llm=True, skip_fuzzer=True)
    assert len(results) == 1
    assert results[0].name == "codeql"
