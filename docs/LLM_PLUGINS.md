# Adding an LLM plugin

FutagAssist uses **plugins** for LLM backends. You can add a new provider by placing a Python module under the `plugins/` directory and implementing the `LLMProvider` protocol.

## 1. Plugin location

- Create a file under `plugins/` (e.g. `plugins/llm/openai_provider.py`).
- The file must be a `.py` module and must **not** start with `_`.
- The CLI loads all such modules from `plugins/` when you run any command (from the project root).

## 2. Implement the provider

Your module must provide:

1. **A class** that implements the `LLMProvider` protocol:
   - **`name: str`** — provider identifier (e.g. `"openai"`).
   - **`complete(self, prompt: str, **kwargs) -> str`** — send a prompt and return the completion text.
   - **`check_health(self) -> bool`** — return `True` if the provider is reachable and working.

2. **A `register(registry)` function** that registers the class with the given `ComponentRegistry`.

The registry passes **environment variables** (from `.env`) as keyword arguments when creating the provider. So your constructor can accept e.g. `api_key`, `model`, `base_url` and read them from the env dict (keys are typically `OPENAI_API_KEY`, `OPENAI_MODEL`, etc., but the loader passes the raw env; you can normalize in the plugin).

## 3. Example skeleton

```python
# plugins/llm/my_llm.py
from futagassist.core.registry import ComponentRegistry
from futagassist.protocols import LLMProvider

class MyLLMProvider:
    name = "my_llm"

    def __init__(self, api_key: str = "", model: str = "default", **kwargs):
        self._api_key = api_key
        self._model = model

    def complete(self, prompt: str, **kwargs) -> str:
        # Call your API and return the completion text.
        return "..."

    def check_health(self) -> bool:
        # Try a minimal request; return True if OK.
        return True

def register(registry: ComponentRegistry) -> None:
    registry.register_llm("my_llm", MyLLMProvider)
```

## 4. Configure FutagAssist to use it

- Set **`LLM_PROVIDER`** in `.env` to the name you used in `register_llm()` (e.g. `my_llm`).
- Set any env vars your plugin expects (e.g. `OPENAI_API_KEY`, `OPENAI_MODEL`). The build stage and health checker pass the raw `.env` dict as kwargs when creating the provider, so your constructor receives **exact env names** (e.g. `OPENAI_API_KEY`, `OPENAI_MODEL`).

## 5. Verify

From the project root (where `plugins/` and `.env` live):

```bash
futagassist check
```

If the LLM plugin is registered and healthy, you’ll see the LLM check OK. You can also run:

```bash
futagassist plugins list
```

to see that your plugin file was loaded.

## 6. Example: OpenAI plugin

An example **OpenAI** plugin is provided in `plugins/llm/openai_provider.py`. It registers as `"openai"` and uses:

- `OPENAI_API_KEY` — API key (required).
- `OPENAI_MODEL` — model name (e.g. `gpt-4.1-mini`).
- `OPENAI_BASE_URL` — optional base URL (for proxies or compatible servers).

Install the OpenAI client and set `.env`:

```bash
pip install openai
```

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
LLM_PROVIDER=openai
```

Then run `futagassist check` and use `futagassist build`; the build stage will use the LLM for README analysis and for fix suggestions on failure.
