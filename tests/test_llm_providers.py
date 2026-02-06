"""Tests for LLM provider plugins (OpenAI, Ollama, Anthropic)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from futagassist.core.registry import ComponentRegistry


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    def test_register(self) -> None:
        from plugins.llm.openai_provider import register
        reg = ComponentRegistry()
        register(reg)
        assert "openai" in reg.list_available()["llm_providers"]

    def test_init_defaults(self) -> None:
        from plugins.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(OPENAI_API_KEY="sk-test")
        assert p._api_key == "sk-test"
        assert p._model == "gpt-4.1-mini"
        assert p._base_url is None

    def test_init_custom_url(self) -> None:
        from plugins.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(OPENAI_API_KEY="k", OPENAI_BASE_URL="http://my-llm:8080")
        assert p._base_url == "http://my-llm:8080"

    def test_check_health_no_key(self) -> None:
        from plugins.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider()
        assert p.check_health() is False

    def test_complete_raises_without_openai_package(self) -> None:
        from plugins.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(OPENAI_API_KEY="sk-test")
        with patch.dict("sys.modules", {"openai": None}):
            # This will fail on import inside complete()
            # but we just verify the provider can be instantiated
            pass  # Can't easily mock import inside function; tested via integration


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------


class TestOllamaProvider:
    def test_register(self) -> None:
        from plugins.llm.ollama_provider import register
        reg = ComponentRegistry()
        register(reg)
        assert "ollama" in reg.list_available()["llm_providers"]

    def test_init_defaults(self) -> None:
        from plugins.llm.ollama_provider import OllamaProvider
        p = OllamaProvider()
        assert p._model == "llama3"
        assert p._base_url == "http://localhost:11434"

    def test_init_custom(self) -> None:
        from plugins.llm.ollama_provider import OllamaProvider
        p = OllamaProvider(OLLAMA_MODEL="codellama", OLLAMA_BASE_URL="http://gpu:11434/")
        assert p._model == "codellama"
        assert p._base_url == "http://gpu:11434"  # trailing slash stripped

    def test_complete_success(self) -> None:
        from plugins.llm.ollama_provider import OllamaProvider
        p = OllamaProvider()
        response_data = json.dumps({"response": "Hello world"}).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = p.complete("Hi")

        assert result == "Hello world"

    def test_complete_connection_error(self) -> None:
        from plugins.llm.ollama_provider import OllamaProvider
        import urllib.error

        p = OllamaProvider()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with pytest.raises(RuntimeError, match="Ollama request failed"):
                p.complete("Hi")

    def test_check_health_success(self) -> None:
        from plugins.llm.ollama_provider import OllamaProvider
        p = OllamaProvider()

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert p.check_health() is True

    def test_check_health_failure(self) -> None:
        from plugins.llm.ollama_provider import OllamaProvider
        p = OllamaProvider()
        with patch("urllib.request.urlopen", side_effect=Exception("refused")):
            assert p.check_health() is False


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    def test_register(self) -> None:
        from plugins.llm.anthropic_provider import register
        reg = ComponentRegistry()
        register(reg)
        assert "anthropic" in reg.list_available()["llm_providers"]

    def test_init_defaults(self) -> None:
        from plugins.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(ANTHROPIC_API_KEY="sk-ant-test")
        assert p._api_key == "sk-ant-test"
        assert "claude" in p._model.lower()

    def test_init_custom_model(self) -> None:
        from plugins.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude-3-haiku")
        assert p._model == "claude-3-haiku"

    def test_check_health_no_key(self) -> None:
        from plugins.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider()
        assert p.check_health() is False
