# Configuration Guide

FutagAssist is configured via YAML files and environment variables. Configuration is loaded from multiple sources with clear precedence rules.

## Configuration Sources (precedence order)

1. **Command-line flags** (highest priority)
2. **Environment variables** (from `.env` or shell)
3. **YAML config file** (`config/default.yaml`)
4. **Built-in defaults** (lowest priority)

## YAML Configuration

Place a `config/default.yaml` in your project root:

```yaml
# LLM provider: openai, ollama, anthropic
llm_provider: openai

# Fuzzer engine: libfuzzer, aflpp
fuzzer_engine: libfuzzer

# Target language: cpp
language: cpp

# Reporter formats
reporters:
  - json
  - sarif
  - html

# CodeQL home (optional)
codeql_home: /opt/codeql

# LLM settings
llm:
  model: gpt-4
  max_retries: 3
  temperature: 0.2

# Fuzzer settings
fuzzer:
  timeout: 10
  max_total_time: 300
  fork: 1
  rss_limit_mb: 2048

# Pipeline configuration
pipeline:
  stages:
    - build
    - analyze
    - generate
    - fuzz_build
    - compile
    - fuzz
    - report
  skip_stages: []
  stop_on_failure: true
```

## Environment Variables

Create a `.env` file in your project root:

```bash
# LLM Configuration
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=               # custom endpoint (optional)

# Or use Ollama (local, no key needed)
# LLM_PROVIDER=ollama
# OLLAMA_MODEL=codellama
# OLLAMA_BASE_URL=http://localhost:11434

# Or use Anthropic
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-sonnet-4-20250514

# Fuzzer engine
FUZZER_ENGINE=libfuzzer

# Language
LANGUAGE=cpp

# CodeQL
CODEQL_HOME=/opt/codeql
```

### Environment Variable Mapping

| Environment Variable | Config Key | Description |
|---------------------|------------|-------------|
| `LLM_PROVIDER` | `llm_provider` | LLM provider name |
| `FUZZER_ENGINE` | `fuzzer_engine` | Fuzzer engine name |
| `LANGUAGE` | `language` | Target language |
| `CODEQL_HOME` | `codeql_home` | CodeQL installation path |
| `OPENAI_API_KEY` | (provider) | OpenAI API key |
| `OPENAI_MODEL` | (provider) | OpenAI model name |
| `OLLAMA_MODEL` | (provider) | Ollama model name |
| `ANTHROPIC_API_KEY` | (provider) | Anthropic API key |

## Configuration Sections

### `llm` — LLM Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model` | string | `gpt-4` | Model name |
| `max_retries` | int | `3` | Max retry attempts for LLM-assisted fixing |
| `temperature` | float | `0.2` | Generation temperature |

### `fuzzer` — Fuzzer Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `timeout` | int | `10` | Per-testcase timeout (seconds) |
| `max_total_time` | int | `300` | Total fuzzing time per binary (seconds) |
| `fork` | int | `1` | Fork worker count |
| `rss_limit_mb` | int | `2048` | RSS memory limit (MB) |

### `pipeline` — Pipeline Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `stages` | list | `[build, analyze, ...]` | Ordered list of stages to execute |
| `skip_stages` | list | `[]` | Stages to skip |
| `stop_on_failure` | bool | `true` | Stop pipeline on first failure |

## Pipeline Stages

The full pipeline runs these stages in order:

| # | Stage | CLI Command | Description |
|---|-------|-------------|-------------|
| 1 | `build` | `futagassist build` | Create CodeQL database |
| 2 | `analyze` | `futagassist analyze` | Extract functions via CodeQL |
| 3 | `generate` | `futagassist generate` | Generate fuzz harnesses |
| 4 | `fuzz_build` | `futagassist fuzz-build` | Build library with sanitizers |
| 5 | `compile` | `futagassist compile` | Compile harnesses into binaries |
| 6 | `fuzz` | `futagassist fuzz` | Run fuzzer on binaries |
| 7 | `report` | `futagassist report` | Generate reports |

Run all stages at once with `futagassist run --repo <path>`.

## Examples

### Minimal setup (OpenAI)

```bash
# .env
OPENAI_API_KEY=sk-...

# Run full pipeline
futagassist run --repo /path/to/project
```

### Local LLM with Ollama

```bash
# .env
LLM_PROVIDER=ollama
OLLAMA_MODEL=codellama

# Run with custom stages
futagassist run --repo /path/to/project --skip fuzz,report
```

### CI/CD (no LLM, JSON reports only)

```bash
futagassist run --repo . --no-llm --no-stop-on-failure
```

### Skip specific stages

```bash
# Skip fuzz_build if library is already instrumented
futagassist run --repo . --skip fuzz_build

# Run only analysis and generation
futagassist run --repo . --stages build,analyze,generate
```

See [QUICKSTART.md](QUICKSTART.md) for a step-by-step tutorial and [PLUGINS.md](PLUGINS.md) for plugin configuration.
