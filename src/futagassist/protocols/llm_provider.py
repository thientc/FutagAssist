"""Protocol for LLM backends."""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    """Protocol for LLM backends (OpenAI, Ollama, Anthropic, etc.)."""

    name: str

    def complete(self, prompt: str, **kwargs: object) -> str:
        """Send a prompt and return the completion text."""
        ...

    def check_health(self) -> bool:
        """Verify the provider is reachable and working."""
        ...
