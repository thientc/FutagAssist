"""Tests for AnalyzeStage."""

from __future__ import annotations

from pathlib import Path

from futagassist.core.config import ConfigManager
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import FunctionInfo, PipelineContext, UsageContext
from futagassist.stages.analyze_stage import AnalyzeStage


class _MockLanguage:
    """Minimal language analyzer that returns a fixed list."""
    language = "mock"

    def get_codeql_queries(self):
        return []

    def extract_functions(self, db_path):
        return [
            FunctionInfo(name="foo", signature="void foo()", file_path="a.c", line=1),
            FunctionInfo(name="bar", signature="int bar(int)", parameters=["int x"], return_type="int"),
        ]

    def extract_usage_contexts(self, db_path):
        return [
            UsageContext(name="init_use_cleanup", calls=["init", "process", "cleanup"], source_file="main.c", source_line=10),
        ]

    def generate_harness_template(self, func: FunctionInfo) -> str:
        return ""

    def get_compiler_flags(self) -> list[str]:
        return []


def test_analyze_stage_no_db_path() -> None:
    """When db_path is None, stage returns failure."""
    stage = AnalyzeStage()
    ctx = PipelineContext(repo_path=None, db_path=None, config={})
    result = stage.execute(ctx)
    assert result.success is False
    assert "db_path" in result.message.lower()


def test_analyze_stage_no_registry() -> None:
    """When registry is not in context, stage returns failure."""
    stage = AnalyzeStage()
    db = Path("/nonexistent/db")
    ctx = PipelineContext(repo_path=None, db_path=db, config={})
    result = stage.execute(ctx)
    assert result.success is False
    assert "registry" in result.message.lower() or "config" in result.message.lower()


def test_analyze_stage_no_language_analyzer(tmp_path: Path) -> None:
    """When no language analyzer is registered for the language, stage returns failure."""
    (tmp_path / "codeql-db").mkdir()
    registry = ComponentRegistry()
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()
    ctx = PipelineContext(
        repo_path=tmp_path,
        db_path=tmp_path / "codeql-db",
        language="cpp",
        config={"registry": registry, "config_manager": config_mgr},
    )
    stage = AnalyzeStage()
    result = stage.execute(ctx)
    assert result.success is False
    assert "language" in result.message.lower() or "analyzer" in result.message.lower()


def test_analyze_stage_success_with_mock_language(tmp_path: Path) -> None:
    """With a registered language analyzer and valid db path, stage returns functions."""
    (tmp_path / "codeql-db").mkdir()
    registry = ComponentRegistry()
    registry.register_language("mock", _MockLanguage)
    from futagassist.reporters import register_builtin_reporters
    register_builtin_reporters(registry)
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()
    ctx = PipelineContext(
        repo_path=tmp_path,
        db_path=tmp_path / "codeql-db",
        language="mock",
        config={"registry": registry, "config_manager": config_mgr},
    )
    stage = AnalyzeStage()
    result = stage.execute(ctx)
    assert result.success is True
    assert "functions" in result.data
    assert len(result.data["functions"]) == 2
    assert result.data["functions"][0].name == "foo"
    assert "usage_contexts" in result.data
    assert len(result.data["usage_contexts"]) == 1
    assert result.data["usage_contexts"][0].calls == ["init", "process", "cleanup"]


def test_analyze_stage_writes_json_when_output_set(tmp_path: Path) -> None:
    """When analyze_output is set, reporter writes JSON file."""
    (tmp_path / "codeql-db").mkdir()
    out_json = tmp_path / "out" / "functions.json"
    registry = ComponentRegistry()
    registry.register_language("mock", _MockLanguage)
    from futagassist.reporters import register_builtin_reporters
    register_builtin_reporters(registry)
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()
    ctx = PipelineContext(
        repo_path=tmp_path,
        db_path=tmp_path / "codeql-db",
        language="mock",
        config={
            "registry": registry,
            "config_manager": config_mgr,
            "analyze_output": str(out_json),
        },
    )
    stage = AnalyzeStage()
    result = stage.execute(ctx)
    assert result.success is True
    assert out_json.is_file()
    import json
    data = json.loads(out_json.read_text())
    assert "functions" in data
    assert len(data["functions"]) == 2
    assert "usage_contexts" in data
    assert len(data["usage_contexts"]) == 1
    assert data["usage_contexts"][0]["calls"] == ["init", "process", "cleanup"]


def test_analyze_stage_can_skip_returns_false() -> None:
    """can_skip always returns False (analysis is always run)."""
    stage = AnalyzeStage()
    ctx = PipelineContext(repo_path=Path("/r"), db_path=Path("/db"), config={})
    assert stage.can_skip(ctx) is False


def test_analyze_stage_with_llm_merges_usage_contexts(tmp_path: Path) -> None:
    """With mock LLM that returns one usage context, result contains analyzer + LLM-suggested contexts."""
    (tmp_path / "codeql-db").mkdir()
    registry = ComponentRegistry()
    registry.register_language("mock", _MockLanguage)
    from futagassist.reporters import register_builtin_reporters
    register_builtin_reporters(registry)

    class MockLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            return "foo_bar: foo, bar"

    registry.register_llm("openai", MockLLM)

    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()
    ctx = PipelineContext(
        repo_path=tmp_path,
        db_path=tmp_path / "codeql-db",
        language="mock",
        config={"registry": registry, "config_manager": config_mgr},
    )
    stage = AnalyzeStage()
    result = stage.execute(ctx)
    assert result.success is True
    ucs = result.data["usage_contexts"]
    assert len(ucs) >= 2
    names_and_calls = [(u.name, tuple(u.calls)) for u in ucs]
    assert ("init_use_cleanup", ("init", "process", "cleanup")) in names_and_calls or any(
        "init" in u.calls for u in ucs
    )
    assert ("foo_bar", ("foo", "bar")) in names_and_calls


def test_analyze_stage_no_llm_succeeds_analyzer_only(tmp_path: Path) -> None:
    """With no LLM registered, stage succeeds with analyzer output only."""
    (tmp_path / "codeql-db").mkdir()
    registry = ComponentRegistry()
    registry.register_language("mock", _MockLanguage)
    from futagassist.reporters import register_builtin_reporters
    register_builtin_reporters(registry)
    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()
    ctx = PipelineContext(
        repo_path=tmp_path,
        db_path=tmp_path / "codeql-db",
        language="mock",
        config={"registry": registry, "config_manager": config_mgr},
    )
    stage = AnalyzeStage()
    result = stage.execute(ctx)
    assert result.success is True
    assert len(result.data["usage_contexts"]) == 1
    assert result.data["usage_contexts"][0].calls == ["init", "process", "cleanup"]


def test_analyze_stage_llm_raises_succeeds_analyzer_only(tmp_path: Path) -> None:
    """When LLM.complete raises, stage still succeeds with analyzer output only."""
    (tmp_path / "codeql-db").mkdir()
    registry = ComponentRegistry()
    registry.register_language("mock", _MockLanguage)
    from futagassist.reporters import register_builtin_reporters
    register_builtin_reporters(registry)

    class FailingLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            raise RuntimeError("API error")

    registry.register_llm("openai", FailingLLM)

    config_mgr = ConfigManager(project_root=tmp_path)
    config_mgr._config_path = tmp_path / "nonexistent.yaml"
    config_mgr.load()
    ctx = PipelineContext(
        repo_path=tmp_path,
        db_path=tmp_path / "codeql-db",
        language="mock",
        config={"registry": registry, "config_manager": config_mgr},
    )
    stage = AnalyzeStage()
    result = stage.execute(ctx)
    assert result.success is True
    assert len(result.data["usage_contexts"]) == 1
    assert result.data["usage_contexts"][0].calls == ["init", "process", "cleanup"]
