"""OpenAI-compatible LLM plugin for FutagAssist.

Register as "openai". Expects .env (or kwargs): OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL (optional).

Install: pip install openai
"""

from __future__ import annotations

from futagassist.core.registry import ComponentRegistry


class OpenAIProvider:
    """LLM provider for OpenAI (or OpenAI-compatible) API."""

    name = "openai"

    def __init__(
        self,
        OPENAI_API_KEY: str = "",
        OPENAI_MODEL: str = "gpt-4.1-mini",
        OPENAI_BASE_URL: str = "",
        **kwargs: object,
    ) -> None:
        self._api_key = OPENAI_API_KEY or (kwargs.get("api_key") if isinstance(kwargs.get("api_key"), str) else "")
        self._model = OPENAI_MODEL or "gpt-4.1-mini"
        self._base_url = OPENAI_BASE_URL.strip() or None

    def complete(self, prompt: str, **kwargs: object) -> str:
        """Send prompt to OpenAI and return completion text."""
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("OpenAI plugin requires 'openai' package. Install with: pip install openai") from e

        client_kwargs: dict = {"api_key": self._api_key}
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        client = OpenAI(**client_kwargs)

        model = kwargs.get("model") if isinstance(kwargs.get("model"), str) else self._model
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", 2048),
            temperature=kwargs.get("temperature", 0.2),
        )
        if not resp.choices:
            return ""
        return (resp.choices[0].message.content or "").strip()

    def check_health(self) -> bool:
        """Verify the API key and endpoint work."""
        if not self._api_key:
            return False
        try:
            self.complete("Hi", max_tokens=5)
            return True
        except Exception:
            return False


def register(registry: ComponentRegistry) -> None:
    """Register the OpenAI LLM provider."""
    registry.register_llm("openai", OpenAIProvider)
