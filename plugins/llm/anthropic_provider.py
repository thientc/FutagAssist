"""Anthropic LLM plugin for FutagAssist.

Register as "anthropic". Expects .env (or kwargs): ANTHROPIC_API_KEY, ANTHROPIC_MODEL (optional).

Install: pip install anthropic
"""

from __future__ import annotations

import logging

from futagassist.core.registry import ComponentRegistry

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-20250514"


class AnthropicProvider:
    """LLM provider for Anthropic Claude API."""

    name = "anthropic"

    def __init__(
        self,
        ANTHROPIC_API_KEY: str = "",
        ANTHROPIC_MODEL: str = "",
        **kwargs: object,
    ) -> None:
        self._api_key = ANTHROPIC_API_KEY or (
            kwargs.get("api_key") if isinstance(kwargs.get("api_key"), str) else ""
        )
        self._model = ANTHROPIC_MODEL or str(kwargs.get("model", "")) or _DEFAULT_MODEL

    def complete(self, prompt: str, **kwargs: object) -> str:
        """Send prompt to Anthropic Messages API and return the response text."""
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError(
                "Anthropic plugin requires 'anthropic' package. Install with: pip install anthropic"
            ) from e

        client = Anthropic(api_key=self._api_key)
        model = kwargs.get("model") if isinstance(kwargs.get("model"), str) else self._model
        max_tokens = kwargs.get("max_tokens", 2048)
        if not isinstance(max_tokens, int):
            max_tokens = 2048
        temperature = kwargs.get("temperature", 0.2)
        if not isinstance(temperature, (int, float)):
            temperature = 0.2

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        if not message.content:
            return ""
        # Content blocks can be text or other types
        parts = []
        for block in message.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts).strip()

    def check_health(self) -> bool:
        """Verify the API key works."""
        if not self._api_key:
            return False
        try:
            self.complete("Hi", max_tokens=5)
            return True
        except Exception:
            return False


def register(registry: ComponentRegistry) -> None:
    """Register the Anthropic LLM provider."""
    registry.register_llm("anthropic", AnthropicProvider)
