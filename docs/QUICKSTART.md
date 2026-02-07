# Quick Start Guide

Get started with FutagAssist in 5 minutes.

## Prerequisites

- **Python 3.10+**
- **CodeQL CLI** (or CodeQL bundle) — [Install guide](https://github.com/github/codeql-cli-binaries)
- **Clang/LLVM** — for compiling fuzz targets with sanitizers
- **LLM API key** (optional) — OpenAI, Ollama (local), or Anthropic

## Installation

```bash
# Clone and install
git clone https://github.com/example/FutagAssist.git
cd FutagAssist
pip install -e .

# Verify installation
futagassist --version
futagassist check
```

## Configuration

Create a `.env` file in your project root:

```bash
# Required for LLM features (optional without LLM)
OPENAI_API_KEY=sk-your-key-here

# CodeQL path (if not on PATH)
CODEQL_HOME=/opt/codeql
```

## Usage

### Full Pipeline (one command)

```bash
futagassist run --repo /path/to/your/c-project
```

This runs all stages automatically:

```
────────────────────────────────────────────────────────────
  [1/7] Stage: build
────────────────────────────────────────────────────────────
  ✓ build: OK (45.2s)

────────────────────────────────────────────────────────────
  [2/7] Stage: analyze
────────────────────────────────────────────────────────────
  ✓ analyze: OK (12.3s)

  ... (more stages) ...

════════════════════════════════════════════════════════════
  Pipeline Summary
════════════════════════════════════════════════════════════
  ✓ build: ...
  ✓ analyze: ...
  ✓ generate: Generated 15 harnesses (12 valid)
  ✓ fuzz_build: ...
  ✓ compile: Compiled 12/12 harnesses
  ✓ fuzz: 3 unique crashes
  ✓ report: Generated 9 report files in 3 formats

  Total: 7 succeeded, 0 failed, 0 skipped
  Duration: 8m 30s
  Result: SUCCESS
════════════════════════════════════════════════════════════
```

### Stage-by-Stage

You can also run stages individually:

```bash
# 1. Build CodeQL database
futagassist build --repo /path/to/project

# 2. Analyze functions
futagassist analyze --db /path/to/project/codeql-db --output functions.json

# 3. Generate fuzz harnesses
futagassist generate --functions functions.json --output fuzz_targets/

# 4. Build library with sanitizers
futagassist fuzz-build --repo /path/to/project

# 5. Compile harnesses
futagassist compile --targets fuzz_targets/ --prefix install-fuzz/

# 6. Run fuzzer
futagassist fuzz --binaries fuzz_binaries/

# 7. Generate reports
futagassist report --results fuzz_results/ --format json --format html
```

### Common Options

```bash
# Skip specific stages
futagassist run --repo . --skip fuzz_build,fuzz

# Run only specific stages
futagassist run --repo . --stages build,analyze,generate

# Disable LLM (template-only generation)
futagassist run --repo . --no-llm

# Continue after failures
futagassist run --repo . --no-stop-on-failure

# Verbose output
futagassist run --repo . -v
```

## Output Structure

After a full pipeline run, your project will contain:

```
project/
├── codeql-db/           # CodeQL database (build stage)
├── install-fuzz/        # Instrumented library (fuzz-build stage)
├── fuzz_targets/        # Generated harness sources (generate stage)
│   ├── api/             # API function harnesses
│   ├── usage_contexts/  # Usage context harnesses
│   └── other/           # Other function harnesses
├── fuzz_binaries/       # Compiled binaries (compile stage)
├── fuzz_results/        # Fuzzing results (fuzz stage)
│   └── fuzz_foo/
│       ├── corpus/      # Test corpus
│       └── artifacts/   # Crash/leak/timeout artifacts
└── reports/             # Reports (report stage)
    ├── json/
    │   ├── functions.json
    │   ├── crashes.json
    │   └── coverage.json
    ├── sarif/
    │   ├── functions.sarif
    │   ├── crashes.sarif
    │   └── coverage.sarif
    └── html/
        ├── functions.html
        ├── crashes.html
        └── coverage.html
```

## Health Check

Verify your setup:

```bash
futagassist check -v
```

```
  CodeQL: OK
    CodeQL version 2.x.x found
  LLM: OK
    OpenAI API key configured
  Fuzzer: OK
    clang and clang++ found
  Plugins: OK
    cpp analyzer registered
All checks passed.
```

## Using with Local LLM (Ollama)

```bash
# Install and start Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull codellama

# Configure
echo "LLM_PROVIDER=ollama" > .env
echo "OLLAMA_MODEL=codellama" >> .env

# Run
futagassist run --repo /path/to/project
```

## CI/CD Integration

```yaml
# GitHub Actions example
- name: Run FutagAssist
  run: |
    pip install -e .
    futagassist run --repo . --no-llm --no-stop-on-failure
    
- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: reports/sarif/crashes.sarif
```

See [CONFIGURATION.md](CONFIGURATION.md) for full configuration reference and [PLUGINS.md](PLUGINS.md) for available plugins.
