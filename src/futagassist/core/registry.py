"""Central registry for all pluggable components."""

from __future__ import annotations

from typing import Any, TypeVar

from futagassist.core.exceptions import RegistryError
from futagassist.protocols import (
    FuzzerEngine,
    LanguageAnalyzer,
    LLMProvider,
    PipelineStage,
    Reporter,
)

T = TypeVar("T")


class ComponentRegistry:
    """Central registry for all pluggable components."""

    def __init__(self) -> None:
        self._llm_providers: dict[str, type[LLMProvider]] = {}
        self._fuzzer_engines: dict[str, type[FuzzerEngine]] = {}
        self._language_analyzers: dict[str, type[LanguageAnalyzer]] = {}
        self._reporters: dict[str, type[Reporter]] = {}
        self._stages: dict[str, type[PipelineStage]] = {}
        self._llm_options: dict[str, dict[str, Any]] = {}
        self._fuzzer_options: dict[str, dict[str, Any]] = {}

    def register_llm(self, name: str, cls: type[LLMProvider], **options: Any) -> None:
        """Register an LLM provider class."""
        self._llm_providers[name] = cls
        if options:
            self._llm_options[name] = options

    def register_fuzzer(self, name: str, cls: type[FuzzerEngine], **options: Any) -> None:
        """Register a fuzzer engine class."""
        self._fuzzer_engines[name] = cls
        if options:
            self._fuzzer_options[name] = options

    def register_language(self, lang: str, cls: type[LanguageAnalyzer]) -> None:
        """Register a language analyzer class."""
        self._language_analyzers[lang] = cls

    def register_reporter(self, fmt: str, cls: type[Reporter]) -> None:
        """Register a reporter class."""
        self._reporters[fmt] = cls

    def register_stage(self, name: str, cls: type[PipelineStage]) -> None:
        """Register a pipeline stage class."""
        self._stages[name] = cls

    def get_llm(self, name: str, **kwargs: Any) -> LLMProvider:
        """Get an LLM provider instance by name."""
        if name not in self._llm_providers:
            raise RegistryError(f"Unknown LLM provider: {name}")
        cls = self._llm_providers[name]
        opts = {**self._llm_options.get(name, {}), **kwargs}
        return cls(**opts)  # type: ignore[call-arg]

    def get_fuzzer(self, name: str, **kwargs: Any) -> FuzzerEngine:
        """Get a fuzzer engine instance by name."""
        if name not in self._fuzzer_engines:
            raise RegistryError(f"Unknown fuzzer engine: {name}")
        cls = self._fuzzer_engines[name]
        opts = {**self._fuzzer_options.get(name, {}), **kwargs}
        return cls(**opts)  # type: ignore[call-arg]

    def get_language(self, lang: str) -> LanguageAnalyzer:
        """Get a language analyzer instance by language."""
        if lang not in self._language_analyzers:
            raise RegistryError(f"Unknown language: {lang}")
        cls = self._language_analyzers[lang]
        return cls()  # type: ignore[call-arg]

    def get_reporter(self, fmt: str) -> Reporter:
        """Get a reporter instance by format name."""
        if fmt not in self._reporters:
            raise RegistryError(f"Unknown reporter format: {fmt}")
        cls = self._reporters[fmt]
        return cls()  # type: ignore[call-arg]

    def get_stage(self, name: str) -> PipelineStage:
        """Get a pipeline stage instance by name."""
        if name not in self._stages:
            raise RegistryError(f"Unknown pipeline stage: {name}")
        cls = self._stages[name]
        return cls()  # type: ignore[call-arg]

    def list_available(self) -> dict[str, list[str]]:
        """Return all registered component names by category."""
        return {
            "llm_providers": list(self._llm_providers),
            "fuzzer_engines": list(self._fuzzer_engines),
            "language_analyzers": list(self._language_analyzers),
            "reporters": list(self._reporters),
            "stages": list(self._stages),
        }
