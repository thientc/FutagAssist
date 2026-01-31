"""Tests for LLM-assisted analysis (suggest_usage_contexts)."""

from __future__ import annotations

from pathlib import Path

from futagassist.analysis.llm_analyze import suggest_usage_contexts
from futagassist.core.schema import FunctionInfo, UsageContext


def test_suggest_usage_contexts_empty_functions_returns_empty() -> None:
    """When functions is empty, returns [] without calling LLM."""
    class MockLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            return "init_use_cleanup: init, use, cleanup"

    result = suggest_usage_contexts(MockLLM(), [], [])
    assert result == []


def test_suggest_usage_contexts_no_complete_returns_empty() -> None:
    """When llm has no complete method, returns []."""
    result = suggest_usage_contexts(object(), [FunctionInfo(name="f", signature="void f()")], [])
    assert result == []


def test_suggest_usage_contexts_well_formed_response_parsed() -> None:
    """When LLM returns well-formed lines, parsed UsageContext list is returned."""
    class MockLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            return "init_use_cleanup: init, process, cleanup"

    functions = [
        FunctionInfo(name="init", signature="void init()"),
        FunctionInfo(name="process", signature="void process()"),
        FunctionInfo(name="cleanup", signature="void cleanup()"),
    ]
    result = suggest_usage_contexts(MockLLM(), functions, [])
    assert len(result) == 1
    assert result[0].name == "init_use_cleanup"
    assert result[0].calls == ["init", "process", "cleanup"]


def test_suggest_usage_contexts_malformed_response_skips_invalid_lines() -> None:
    """When LLM returns malformed lines, valid lines are parsed and invalid skipped."""
    class MockLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            return "good: a, b\nbad line\nanother: b, a"

    functions = [
        FunctionInfo(name="a", signature="void a()"),
        FunctionInfo(name="b", signature="void b()"),
    ]
    result = suggest_usage_contexts(MockLLM(), functions, [])
    assert len(result) == 2
    assert result[0].calls == ["a", "b"]
    assert result[1].calls == ["b", "a"]


def test_suggest_usage_contexts_unknown_function_skipped() -> None:
    """When a call is not in the function list, that line is skipped."""
    class MockLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            return "bad: init, not_a_function, cleanup"

    functions = [
        FunctionInfo(name="init", signature="void init()"),
        FunctionInfo(name="cleanup", signature="void cleanup()"),
    ]
    result = suggest_usage_contexts(MockLLM(), functions, [])
    assert result == []


def test_suggest_usage_contexts_llm_raises_returns_empty() -> None:
    """When LLM.complete raises, returns []."""
    class MockLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            raise RuntimeError("API error")

    functions = [FunctionInfo(name="f", signature="void f()")]
    result = suggest_usage_contexts(MockLLM(), functions, [])
    assert result == []


def test_suggest_usage_contexts_empty_response_returns_empty() -> None:
    """When LLM returns empty string, returns []."""
    class MockLLM:
        def complete(self, prompt: str, **kwargs: object) -> str:
            return ""

    functions = [FunctionInfo(name="f", signature="void f()")]
    result = suggest_usage_contexts(MockLLM(), functions, [])
    assert result == []
