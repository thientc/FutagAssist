# Built-in Plugins

This document describes all built-in plugins shipped with FutagAssist. Plugins are loaded automatically from the `plugins/` directory via the `PluginLoader`, or registered directly as built-in components.

## Overview

| Category | Plugin | Registered Name | Location |
|----------|--------|-----------------|----------|
| **LLM Providers** | OpenAI | `openai` | `plugins/llm/openai_provider.py` |
| | Ollama | `ollama` | `plugins/llm/ollama_provider.py` |
| | Anthropic | `anthropic` | `plugins/llm/anthropic_provider.py` |
| **Fuzzer Engines** | libFuzzer | `libfuzzer` | `plugins/fuzzer/libfuzzer_engine.py` |
| | AFL++ | `aflpp` | `plugins/fuzzer/aflpp_engine.py` |
| **Language Analyzers** | C/C++ | `cpp` | `plugins/cpp/cpp_analyzer.py` |
| **Reporters** | JSON | `json` | `src/futagassist/reporters/json_reporter.py` |
| | SARIF | `sarif` | `src/futagassist/reporters/sarif_reporter.py` |
| | HTML | `html` | `src/futagassist/reporters/html_reporter.py` |

---

## LLM Providers

All LLM providers implement the `LLMProvider` protocol:

```python
class LLMProvider(Protocol):
    name: str
    def complete(self, prompt: str, **kwargs) -> str: ...
    def check_health(self) -> bool: ...
```

### OpenAI (`openai`)

OpenAI-compatible API provider. Works with OpenAI, Azure OpenAI, and any OpenAI-compatible endpoint.

**Installation:** `pip install openai`

**Configuration (.env):**

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | API key |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model name |
| `OPENAI_BASE_URL` | (OpenAI default) | Custom endpoint URL |

**Usage:**
```bash
# In .env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini

# Or set LLM_PROVIDER in config
LLM_PROVIDER=openai
```

### Ollama (`ollama`)

Local inference via Ollama server. No API key required.

**Installation:** [Install Ollama](https://ollama.ai), then `ollama pull llama3`

**Configuration (.env):**

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `llama3` | Model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |

**Usage:**
```bash
# Start Ollama server, then:
LLM_PROVIDER=ollama
OLLAMA_MODEL=codellama
```

**Notes:**
- Uses the `/api/generate` endpoint with `stream: false`
- No external Python packages required (uses `urllib`)
- `check_health()` pings `/api/tags` to verify server availability

### Anthropic (`anthropic`)

Anthropic Claude API provider.

**Installation:** `pip install anthropic`

**Configuration (.env):**

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Model name |

**Usage:**
```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Fuzzer Engines

All fuzzer engines implement the `FuzzerEngine` protocol:

```python
class FuzzerEngine(Protocol):
    name: str
    def fuzz(self, binary: Path, corpus_dir: Path, **options) -> FuzzResult: ...
    def get_coverage(self, binary: Path, profdata: Path) -> CoverageReport: ...
    def parse_crashes(self, artifact_dir: Path) -> list[CrashInfo]: ...
```

### libFuzzer (`libfuzzer`)

LLVM libFuzzer integration. Based on [Futag's fuzzer.py](https://github.com/ispras/Futag/blob/main/src/python/futag-package/src/futag/fuzzer.py).

**Requirements:** Binaries must be compiled with `-fsanitize=fuzzer`

**Fuzz options:**

| Option | Default | Description |
|--------|---------|-------------|
| `timeout` | `30` | Per-testcase timeout (seconds) |
| `max_total_time` | `60` | Total fuzzing time (seconds) |
| `fork` | `1` | Fork worker count |
| `rss_limit_mb` | `2048` | RSS memory limit (MB) |
| `artifact_prefix` | `<corpus>/crash-` | Crash artifact path prefix |

**Features:**
- Runs binaries directly with libFuzzer flags
- Sets `LLVM_PROFILE_FILE` for coverage collection
- Parses `crash-`, `leak-`, `timeout-`, `oom-` artifacts
- Coverage via `llvm-profdata merge` + `llvm-cov export`
- Parses `exec/s` and duration from libFuzzer stderr

### AFL++ (`aflpp`)

Basic AFL++ integration.

**Requirements:** `afl-fuzz` on PATH; binaries compiled with `afl-clang-fast++`

**Fuzz options:**

| Option | Default | Description |
|--------|---------|-------------|
| `timeout` | `1000` | Per-testcase timeout (ms) |
| `max_total_time` | `60` | Total fuzzing time (seconds, `-V` flag) |
| `artifact_prefix` | `<corpus>/../afl_output` | AFL output directory |

**Features:**
- Runs `afl-fuzz` in headless mode (`AFL_NO_UI=1`)
- Auto-creates seed if corpus is empty
- Parses crash files from `<output>/default/crashes/` (AFL++ layout)
- Coverage: not collected by default (AFL++ uses different instrumentation)

---

## Language Analyzers

All language analyzers implement the `LanguageAnalyzer` protocol:

```python
class LanguageAnalyzer(Protocol):
    language: str
    def get_codeql_queries(self) -> list[Path]: ...
    def extract_functions(self, db_path: Path) -> list[FunctionInfo]: ...
    def extract_usage_contexts(self, db_path: Path) -> list[UsageContext]: ...
    def generate_harness_template(self, func: FunctionInfo) -> str: ...
    def get_compiler_flags(self) -> list[str]: ...
```

### C/C++ (`cpp`)

Full-featured C/C++ analyzer using CodeQL.

**Requirements:** CodeQL CLI (or bundle) installed

**CodeQL queries (in `plugins/cpp/`):**

| Query | Purpose |
|-------|---------|
| `list_functions.ql` | Extract all functions with signatures |
| `api_functions.ql` | Identify public API functions |
| `fuzz_targets.ql` | Identify fuzz target candidates |
| `parameter_semantics.ql` | Classify parameter types (buffer, size, file path, etc.) |

**Compiler flags:** `["-fsanitize=fuzzer", "-g"]`

---

## Reporters

All reporters implement the `Reporter` protocol:

```python
class Reporter(Protocol):
    format_name: str
    def report_coverage(self, data: CoverageReport, output: Path) -> None: ...
    def report_crashes(self, crashes: list[CrashInfo], output: Path) -> None: ...
    def report_functions(self, functions: list[FunctionInfo], output: Path) -> None: ...
```

### JSON (`json`)

Machine-readable JSON output. **Built-in** (registered in `reporters/__init__.py`).

**Output files:**
- `functions.json` -- array of function info objects
- `crashes.json` -- array of crash info objects
- `coverage.json` -- coverage report object

### SARIF (`sarif`)

[Static Analysis Results Interchange Format](https://sarifweb.azurewebsites.net/) v2.1.0. **Built-in**.

Compatible with GitHub Code Scanning, Azure DevOps, and other SARIF-consuming tools.

**Output files:**
- `functions.sarif` -- function info as informational results (level: note)
- `crashes.sarif` -- crashes as error results with location info
- `coverage.sarif` -- coverage summary as informational result

### HTML (`html`)

Human-readable standalone HTML pages with tables and progress bars. **Built-in**.

**Output files:**
- `functions.html` -- sortable table of functions with API/Fuzz badges
- `crashes.html` -- table of crashes with type, summary, location
- `coverage.html` -- progress bars for line and region coverage

---

## Writing a Custom Plugin

Plugins are Python modules in the `plugins/` directory that expose a `register(registry)` function.

### Example: Custom LLM Provider

```python
# plugins/llm/my_provider.py
from futagassist.core.registry import ComponentRegistry

class MyProvider:
    name = "my_llm"

    def __init__(self, MY_API_KEY: str = "", **kwargs):
        self._key = MY_API_KEY

    def complete(self, prompt: str, **kwargs) -> str:
        # Call your API
        return "response"

    def check_health(self) -> bool:
        return bool(self._key)

def register(registry: ComponentRegistry) -> None:
    registry.register_llm("my_llm", MyProvider)
```

### Example: Custom Fuzzer Engine

```python
# plugins/fuzzer/my_fuzzer.py
from pathlib import Path
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import CrashInfo, CoverageReport, FuzzResult

class MyFuzzer:
    name = "my_fuzzer"

    def __init__(self, **kwargs): pass

    def fuzz(self, binary: Path, corpus_dir: Path, **options) -> FuzzResult:
        # Run your fuzzer
        return FuzzResult(binary_path=str(binary), corpus_dir=str(corpus_dir), success=True)

    def parse_crashes(self, artifact_dir: Path) -> list[CrashInfo]:
        return []

    def get_coverage(self, binary: Path, profdata: Path) -> CoverageReport:
        return CoverageReport()

def register(registry: ComponentRegistry) -> None:
    registry.register_fuzzer("my_fuzzer", MyFuzzer)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the overall framework design.
