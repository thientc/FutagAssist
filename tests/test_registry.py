"""Tests for ComponentRegistry."""

from __future__ import annotations

import pytest

from futagassist.core.exceptions import RegistryError
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import FunctionInfo
from futagassist.protocols import (
    FuzzerEngine,
    LanguageAnalyzer,
    LLMProvider,
    PipelineStage,
    Reporter,
)


class _MockLLM(LLMProvider):
    name = "mock_llm"

    def complete(self, prompt: str, **kwargs: object) -> str:
        return "ok"

    def check_health(self) -> bool:
        return True


class _MockFuzzer(FuzzerEngine):
    name = "mock_fuzzer"

    def fuzz(self, binary, corpus_dir, **options):
        from futagassist.core.schema import FuzzResult
        return FuzzResult(binary_path=str(binary))

    def get_coverage(self, binary, profdata):
        from futagassist.core.schema import CoverageReport
        return CoverageReport()

    def parse_crashes(self, artifact_dir):
        return []


class _MockLanguage(LanguageAnalyzer):
    language = "mock"

    def get_codeql_queries(self):
        return []

    def extract_functions(self, db_path):
        return []

    def generate_harness_template(self, func: FunctionInfo) -> str:
        return ""

    def get_compiler_flags(self) -> list[str]:
        return []


class _MockReporter(Reporter):
    format_name = "mock"

    def report_coverage(self, data, output):
        pass

    def report_crashes(self, crashes, output):
        pass

    def report_functions(self, functions, output):
        pass


class _MockStage(PipelineStage):
    name = "mock_stage"
    depends_on: list[str] = []

    def execute(self, context):
        from futagassist.core.schema import StageResult
        return StageResult(stage_name=self.name, success=True)

    def can_skip(self, context) -> bool:
        return False


def test_registry_register_and_get_llm() -> None:
    reg = ComponentRegistry()
    reg.register_llm("mock", _MockLLM)
    provider = reg.get_llm("mock")
    assert provider.name == "mock_llm"
    assert provider.complete("hi") == "ok"
    assert provider.check_health() is True


def test_registry_register_and_get_fuzzer() -> None:
    reg = ComponentRegistry()
    reg.register_fuzzer("mock", _MockFuzzer)
    engine = reg.get_fuzzer("mock")
    assert engine.name == "mock_fuzzer"


def test_registry_register_and_get_language() -> None:
    reg = ComponentRegistry()
    reg.register_language("mock", _MockLanguage)
    analyzer = reg.get_language("mock")
    assert analyzer.language == "mock"


def test_registry_register_and_get_reporter() -> None:
    reg = ComponentRegistry()
    reg.register_reporter("mock", _MockReporter)
    reporter = reg.get_reporter("mock")
    assert reporter.format_name == "mock"


def test_registry_register_and_get_stage() -> None:
    reg = ComponentRegistry()
    reg.register_stage("mock", _MockStage)
    stage = reg.get_stage("mock")
    assert stage.name == "mock_stage"


def test_registry_get_unknown_llm_raises() -> None:
    reg = ComponentRegistry()
    with pytest.raises(RegistryError, match="Unknown LLM provider"):
        reg.get_llm("nonexistent")


def test_registry_get_unknown_fuzzer_raises() -> None:
    reg = ComponentRegistry()
    with pytest.raises(RegistryError, match="Unknown fuzzer engine"):
        reg.get_fuzzer("nonexistent")


def test_registry_get_unknown_language_raises() -> None:
    reg = ComponentRegistry()
    with pytest.raises(RegistryError, match="Unknown language"):
        reg.get_language("nonexistent")


def test_registry_get_unknown_reporter_raises() -> None:
    reg = ComponentRegistry()
    with pytest.raises(RegistryError, match="Unknown reporter"):
        reg.get_reporter("nonexistent")


def test_registry_get_unknown_stage_raises() -> None:
    reg = ComponentRegistry()
    with pytest.raises(RegistryError, match="Unknown pipeline stage"):
        reg.get_stage("nonexistent")


def test_registry_list_available_empty() -> None:
    reg = ComponentRegistry()
    avail = reg.list_available()
    assert avail["llm_providers"] == []
    assert avail["fuzzer_engines"] == []
    assert avail["language_analyzers"] == []
    assert avail["reporters"] == []
    assert avail["stages"] == []


def test_registry_list_available_after_register() -> None:
    reg = ComponentRegistry()
    reg.register_llm("mock", _MockLLM)
    reg.register_fuzzer("mock", _MockFuzzer)
    reg.register_stage("mock", _MockStage)
    avail = reg.list_available()
    assert "mock" in avail["llm_providers"]
    assert "mock" in avail["fuzzer_engines"]
    assert "mock" in avail["stages"]
