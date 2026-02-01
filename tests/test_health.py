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
    with patch("futagassist.core.health._run_cmd") as m:
        m.return_value = (True, "2.15.0")
        result = checker.check_codeql(verify_packs=False)
    assert result.name == "codeql"
    assert result.ok is True


def test_health_checker_check_codeql_not_found() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    with patch("futagassist.core.health._run_cmd") as m:
        m.return_value = (False, "command not found")
        result = checker.check_codeql()
    assert result.name == "codeql"
    assert result.ok is False
    assert "not found" in result.message or "command" in result.message.lower()
    assert result.suggestion != ""


def test_health_checker_check_llm_no_provider_registered() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    result = checker.check_llm()
    assert result.name == "llm"
    assert result.ok is False
    assert "openai" in result.message or "registered" in result.message.lower()
    assert result.suggestion != ""


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
    assert result.suggestion != ""


def test_health_checker_check_plugins_no_dir(tmp_path: Path) -> None:
    """When plugins/ does not exist, check_plugins fails with suggestion."""
    config = ConfigManager(project_root=tmp_path)
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    result = checker.check_plugins()
    assert result.name == "plugins"
    assert result.ok is False
    assert "plugins" in result.message.lower()
    assert result.suggestion != ""


def test_health_checker_check_plugins_no_analyzer_for_language(tmp_path: Path) -> None:
    """When plugins/ exists but no analyzer for configured language, check_plugins fails."""
    (tmp_path / "plugins").mkdir(parents=True)
    config = ConfigManager(project_root=tmp_path)
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    result = checker.check_plugins()
    assert result.name == "plugins"
    assert result.ok is False
    assert "cpp" in result.message or "none" in result.message.lower()
    assert result.suggestion != ""


def test_health_checker_check_plugins_ok(tmp_path: Path) -> None:
    """When plugins/ exists and cpp analyzer is registered, check_plugins passes."""
    (tmp_path / "plugins" / "cpp").mkdir(parents=True)
    config = ConfigManager(project_root=tmp_path)
    config.load()
    registry = ComponentRegistry()
    # Register cpp so the check sees a language analyzer
    from tests.test_analyze_stage import _MockLanguage
    registry.register_language("cpp", _MockLanguage)
    checker = HealthChecker(config=config, registry=registry)
    result = checker.check_plugins()
    assert result.name == "plugins"
    assert result.ok is True
    assert "cpp" in result.message or "analyzer" in result.message.lower()


def test_health_checker_check_all_skip_llm() -> None:
    config = ConfigManager(project_root=Path("/nonexistent"))
    config.load()
    registry = ComponentRegistry()
    checker = HealthChecker(config=config, registry=registry)
    results = checker.check_all(skip_llm=True, skip_fuzzer=True, skip_plugins=True)
    assert len(results) == 1
    assert results[0].name == "codeql"
