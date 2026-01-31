# FutagAssist

An intelligent assistant that leverages CodeQL's semantic code analysis and Large Language Models to automatically generate high-quality fuzz targets, dramatically reducing the manual effort required for comprehensive fuzzing campaigns.

## How to build a library with CodeQL

FutagAssist can build a C/C++ (or Python) library and create a **CodeQL database** in one step. It infers build steps from the project’s README/INSTALL and runs the build under `codeql database create`.

**Prerequisites:**

- [CodeQL CLI](https://codeql.github.com/docs/codeql-cli/) on your PATH, or `CODEQL_HOME` set (e.g. in `.env`)
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
