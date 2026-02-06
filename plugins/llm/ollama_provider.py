"""Ollama LLM plugin for FutagAssist.

Register as "ollama". Expects .env (or kwargs): OLLAMA_MODEL, OLLAMA_BASE_URL (optional).
Ollama runs locally—no API key required.

Install: pip install httpx   (or requests; httpx preferred for async compat)
"""

from __future__ import annotations

import json
import logging

from futagassist.core.registry import ComponentRegistry

log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "llama3"


class OllamaProvider:
    """LLM provider for Ollama (local inference server)."""

    name = "ollama"

    def __init__(
        self,
        OLLAMA_MODEL: str = "",
        OLLAMA_BASE_URL: str = "",
        **kwargs: object,
    ) -> None:
        self._model = OLLAMA_MODEL or str(kwargs.get("model", "")) or _DEFAULT_MODEL
        base = OLLAMA_BASE_URL or str(kwargs.get("base_url", "")) or _DEFAULT_BASE_URL
        self._base_url = base.rstrip("/")

    def complete(self, prompt: str, **kwargs: object) -> str:
        """Send prompt to Ollama /api/generate and return the response text."""
        import urllib.request
        import urllib.error

        model = kwargs.get("model") if isinstance(kwargs.get("model"), str) else self._model
        url = f"{self._base_url}/api/generate"
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.2),
                "num_predict": kwargs.get("max_tokens", 2048),
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return (data.get("response") or "").strip()
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Ollama returned invalid JSON: {e}") from e

    def check_health(self) -> bool:
        """Check if Ollama server is reachable."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(f"{self._base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False


def register(registry: ComponentRegistry) -> None:
    """Register the Ollama LLM provider."""
    registry.register_llm("ollama", OllamaProvider)
