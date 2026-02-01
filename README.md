# FutagAssist

An intelligent assistant that leverages CodeQL's semantic code analysis and Large Language Models to automatically generate high-quality fuzz targets, dramatically reducing the manual effort required for comprehensive fuzzing campaigns.

## Quick Start

```bash
# 1. Install FutagAssist
pip install -e .

# 2. Install CodeQL bundle (required)
# See: docs/BUILD_WITH_CODEQL.md#installing-the-codeql-bundle
export CODEQL_HOME=/path/to/codeql-bundle

# 3. Build a library with CodeQL
futagassist build --repo /path/to/library

# 4. Analyze to extract function info
futagassist analyze --db /path/to/library/codeql-db --output functions.json
```

## Pipeline Overview

```
build → analyze → generate → compile → fuzz → report
```

| Stage | Command | Description |
|-------|---------|-------------|
| **Build** | `futagassist build` | Build library with CodeQL, create database |
| **Analyze** | `futagassist analyze` | Extract functions, API info, fuzz candidates |
| Generate | *(coming soon)* | Generate fuzz harnesses using LLM |
| Compile | *(coming soon)* | Compile harnesses with sanitizers |
| Fuzz | *(coming soon)* | Run fuzzing campaign |
| Report | *(coming soon)* | Generate coverage/crash reports |

---

## How to build a library with CodeQL

FutagAssist can build a C/C++ (or Python) library and create a **CodeQL database** in one step. It infers build steps from the project’s README/INSTALL and runs the build under `codeql database create`.

**Prerequisites:**

- **CodeQL bundle** (**required**, not the standalone CLI) — includes the CLI and language packs (e.g. `codeql/cpp-all`). See [Installing the CodeQL Bundle](docs/BUILD_WITH_CODEQL.md#installing-the-codeql-bundle) for step-by-step instructions.
- The library’s build dependencies installed (e.g. autotools, cmake, compilers)
- Optional: LLM configured (see [Adding an LLM plugin](docs/LLM_PLUGINS.md); e.g. `.env` with `OPENAI_API_KEY` and `LLM_PROVIDER=openai`) for better build-step extraction and failure fixes

**Commands:**

```bash
# Build a library and create a CodeQL database (default: <repo>/codeql-db)
futagassist build --repo /path/to/library

# Specify database path and language
futagassist build --repo /path/to/library --output /path/to/codeql-db --language cpp
```

**What it does:**

1. Reads README, INSTALL, BUILD, etc. and extracts build commands (using an LLM if configured, otherwise heuristics).
2. Wraps the build with `codeql database create --language <lang> --command="<build-cmd>"` and runs it.
3. On failure, can ask the LLM for a fix command (e.g. install missing deps) and print it for you to run manually; it does not run the command automatically.
4. Writes the CodeQL database to `--output` or `<repo>/codeql-db`.

**Example with downloaded projects:**

```bash
# 1. Download a project (e.g. into libs/)
python scripts/download_projects.py --project zlib

# 2. Build with CodeQL
futagassist build --repo libs/zlib --language c
# Database is created at libs/zlib/codeql-db (or use --output to override)
```

See [docs/BUILD_WITH_CODEQL.md](docs/BUILD_WITH_CODEQL.md) for more detail and troubleshooting.

---

## Analyze a CodeQL database

After building, use `futagassist analyze` to extract function information for fuzz target generation.

```bash
# Analyze and print function count
futagassist analyze --db /path/to/codeql-db

# Analyze and export to JSON
futagassist analyze --db /path/to/codeql-db --output functions.json
```

**What it extracts:**

- **Function details:** name, signature, return type, parameters, file path, line number
- **API functions:** public functions suitable for fuzzing (header-declared, external linkage)
- **Fuzz target candidates:** functions taking (buffer, size) pairs, C strings, or file handles
- **Call relationships:** caller → callee for understanding usage patterns
- **Init/cleanup pairs:** matching pairs like `open`/`close`, `alloc`/`free`

**Example output (`functions.json`):**

```json
{
  "functions": [
    {
      "name": "png_read_image",
      "signature": "void png_read_image(png_structrp png_ptr, png_bytepp image)",
      "return_type": "void",
      "parameters": ["png_structrp png_ptr", "png_bytepp image"],
      "file_path": "pngread.c",
      "line": 734
    }
  ],
  "usage_contexts": []
}
```

See [docs/ANALYZE_STAGE.md](docs/ANALYZE_STAGE.md) for the full list of CodeQL queries and scoring criteria.

---

## Verify setup (CodeQL, LLM, plugins)

Run `futagassist check` to verify that CodeQL, the configured LLM, plugins (e.g. language analyzers), and the fuzzer engine are working. Failed checks include **suggestions** (paths to set, env vars, or next steps).

```bash
# Full check (CodeQL, plugins, LLM, fuzzer)
futagassist check

# Verbose: show paths and verify CodeQL can resolve QL packs (e.g. cpp)
futagassist check -v

# Skip optional checks
futagassist check --skip-llm --skip-fuzzer --skip-plugins
```

**What is checked:**

- **codeql** — CLI available and version; with `-v`, also that the cpp pack can be resolved (needed for `futagassist analyze`). Suggests `CODEQL_HOME` or adding the bundle to PATH if missing.
- **plugins** — `plugins/` exists and a language analyzer is registered for the configured language (e.g. cpp). Suggests running from the project root or adding `plugins/cpp/`.
- **llm** — Configured provider is registered and `check_health()` passes. Suggests `OPENAI_API_KEY` in `.env` when relevant.
- **fuzzer** — Selected engine (e.g. libfuzzer) is registered and clang is available. Suggests installing LLVM/clang.

---

## Download critical C/C++/Python projects (OSS-Fuzz style)

A config file and script are provided to clone top critical open-source projects used for fuzzing (aligned with [OSS-Fuzz](https://github.com/google/oss-fuzz)).

- **Config:** [`config/libs_projects.yaml`](config/libs_projects.yaml) — list of projects (openssl, curl, libxml2, sqlite, zlib, re2, brotli, cpython, Pillow, etc.) with `name`, `repo_url`, `language`, optional `branch` and `build_type`.
- **Script:** [`scripts/download_projects.py`](scripts/download_projects.py) — clones repos into `libs/` (gitignored).

```bash
# List projects
python scripts/download_projects.py --list
# or: make list-projects

# Download all projects into libs/
python scripts/download_projects.py
# or: make download-projects

# Download a single project (e.g. openssl)
python scripts/download_projects.py --project openssl

# Shallow clone (faster)
python scripts/download_projects.py --shallow
```

See [`scripts/README.md`](scripts/README.md) for full options.
