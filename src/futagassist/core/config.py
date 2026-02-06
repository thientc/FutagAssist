"""Configuration loading from .env and YAML."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


def _find_project_root(start: Path | None = None) -> Path:
    """Find project root by looking for pyproject.toml upward."""
    current = Path(start or Path.cwd()).resolve()
    for _ in range(10):
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.cwd().resolve()


class PipelineConfigModel(BaseModel):
    """Pipeline section of config."""

    stages: list[str] = Field(
        default_factory=lambda: ["build", "analyze", "generate", "fuzz_build", "compile", "fuzz", "report"]
    )
    skip_stages: list[str] = Field(default_factory=list)
    stop_on_failure: bool = True


class LLMConfigModel(BaseModel):
    """LLM section of config."""

    model: str = "gpt-4"
    max_retries: int = 3
    temperature: float = 0.2


class FuzzerConfigModel(BaseModel):
    """Fuzzer section of config."""

    timeout: int = 10
    max_total_time: int = 300
    fork: int = 1
    rss_limit_mb: int = 2048


class AppConfig(BaseModel):
    """Full application configuration."""

    llm_provider: str = "openai"
    fuzzer_engine: str = "libfuzzer"
    language: str = "cpp"
    reporters: list[str] = Field(default_factory=lambda: ["json", "sarif"])
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    fuzzer: FuzzerConfigModel = Field(default_factory=FuzzerConfigModel)
    pipeline: PipelineConfigModel = Field(default_factory=PipelineConfigModel)
    codeql_home: str | None = None


class ConfigManager:
    """Load and merge configuration from .env and YAML."""

    def __init__(
        self,
        project_root: Path | None = None,
        env_path: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._root = Path(project_root or _find_project_root()).resolve()
        self._env_path = Path(env_path) if env_path else self._root / ".env"
        self._config_path = Path(config_path) if config_path else self._root / "config" / "default.yaml"
        self._config: AppConfig | None = None
        self._env: dict[str, str] = {}

    def load_env(self) -> dict[str, str]:
        """Load .env file into a dict (without modifying os.environ)."""
        try:
            from dotenv import dotenv_values
        except ImportError:
            log.debug("python-dotenv not installed; skipping .env loading")
            self._env = {}
            return self._env
        try:
            self._env = dict(dotenv_values(self._env_path))
            return self._env
        except (OSError, PermissionError) as e:
            log.warning("Failed to read .env file %s: %s", self._env_path, e)
            self._env = {}
            return self._env

    def load_yaml(self) -> dict[str, Any]:
        """Load YAML config file if it exists."""
        if not self._config_path.exists():
            return {}
        try:
            import yaml
        except ImportError:
            log.warning("pyyaml not installed; skipping YAML config loading")
            return {}
        try:
            with open(self._config_path) as f:
                return yaml.safe_load(f) or {}
        except (OSError, PermissionError) as e:
            log.warning("Failed to read config file %s: %s", self._config_path, e)
            return {}
        except yaml.YAMLError as e:
            log.warning("Malformed YAML in %s: %s", self._config_path, e)
            return {}

    def load(self) -> AppConfig:
        """Load .env and YAML, merge with defaults, return AppConfig."""
        env = self.load_env()
        yaml_data = self.load_yaml()

        # Build merged dict: YAML first, then env overrides
        config_dict: dict[str, Any] = {
            "llm_provider": yaml_data.get("llm_provider", "openai"),
            "fuzzer_engine": yaml_data.get("fuzzer_engine", "libfuzzer"),
            "language": yaml_data.get("language", "cpp"),
            "reporters": yaml_data.get("reporters", ["json", "sarif"]),
            "codeql_home": yaml_data.get("codeql_home"),
        }
        # Environment variables override YAML values
        env_mapping = {
            "LLM_PROVIDER": "llm_provider",
            "FUZZER_ENGINE": "fuzzer_engine",
            "LANGUAGE": "language",
            "CODEQL_HOME": "codeql_home",
        }
        for env_key, config_key in env_mapping.items():
            if env.get(env_key):
                config_dict[config_key] = env[env_key]

        if "llm" in yaml_data and yaml_data["llm"]:
            config_dict["llm"] = LLMConfigModel(**yaml_data["llm"])
        if "fuzzer" in yaml_data and yaml_data["fuzzer"]:
            config_dict["fuzzer"] = FuzzerConfigModel(**yaml_data["fuzzer"])
        if "pipeline" in yaml_data and yaml_data["pipeline"]:
            config_dict["pipeline"] = PipelineConfigModel(**yaml_data["pipeline"])

        self._config = AppConfig(**config_dict)
        return self._config

    @property
    def config(self) -> AppConfig:
        """Return loaded config; load if not yet loaded."""
        if self._config is None:
            self.load()
        if self._config is None:
            raise RuntimeError("ConfigManager.load() failed to produce a config")
        return self._config

    @property
    def env(self) -> dict[str, str]:
        """Return loaded env dict."""
        if not self._env and self._env_path.exists():
            self.load_env()
        return self._env

    @property
    def project_root(self) -> Path:
        return self._root
