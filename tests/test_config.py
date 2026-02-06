"""Tests for ConfigManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from futagassist.core.config import AppConfig, ConfigManager


def test_config_manager_defaults(tmp_path: Path) -> None:
    """Without .env or YAML, config uses defaults."""
    # Use tmp_path so no project pyproject.toml is found; cwd fallback
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr._env_path = tmp_path / ".env"
    config = config_mgr.load()
    assert config.llm_provider == "openai"
    assert config.fuzzer_engine == "libfuzzer"
    assert config.language == "cpp"
    assert "build" in config.pipeline.stages
    assert config.pipeline.stop_on_failure is True


def test_config_manager_load_yaml(tmp_path: Path) -> None:
    """YAML file overrides defaults."""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("""
llm_provider: ollama
language: python
pipeline:
  stages: [build, analyze]
  stop_on_failure: false
""")
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = yaml_file
    config_mgr._env_path = tmp_path / ".env"
    config = config_mgr.load()
    assert config.llm_provider == "ollama"
    assert config.language == "python"
    assert config.pipeline.stages == ["build", "analyze"]
    assert config.pipeline.stop_on_failure is False


def test_config_manager_env_overrides(tmp_path: Path) -> None:
    """Environment variables override YAML."""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("llm_provider: openai\n")
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=ollama\nCODEQL_HOME=/opt/codeql\n")
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = yaml_file
    config_mgr._env_path = env_file
    config = config_mgr.load()  # load() calls load_env() and merges
    assert config.llm_provider == "ollama"
    assert config.codeql_home == "/opt/codeql"


def test_config_manager_project_root(tmp_path: Path) -> None:
    """Project root is set from constructor."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    config_mgr = ConfigManager(project_root=root)
    assert config_mgr.project_root == root


def test_config_manager_malformed_yaml(tmp_path: Path) -> None:
    """Malformed YAML logs warning and returns defaults."""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("llm_provider: [unterminated\n")
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = yaml_file
    config_mgr._env_path = tmp_path / ".env"
    config = config_mgr.load()
    # Falls back to defaults
    assert config.llm_provider == "openai"


def test_config_manager_env_overrides_fuzzer_and_language(tmp_path: Path) -> None:
    """FUZZER_ENGINE and LANGUAGE env vars override YAML."""
    env_file = tmp_path / ".env"
    env_file.write_text("FUZZER_ENGINE=aflpp\nLANGUAGE=python\n")
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr._env_path = env_file
    config = config_mgr.load()
    assert config.fuzzer_engine == "aflpp"
    assert config.language == "python"


def test_config_manager_fuzz_build_in_default_stages(tmp_path: Path) -> None:
    """Default pipeline stages include fuzz_build."""
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr._env_path = tmp_path / ".env"
    config = config_mgr.load()
    assert "fuzz_build" in config.pipeline.stages
