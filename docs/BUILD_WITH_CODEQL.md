# Building a library with CodeQL using FutagAssist

This guide explains how to use FutagAssist to build a C, C++, or Python library and produce a **CodeQL database** for later analysis and fuzz-target generation.

## Prerequisites

1. **CodeQL CLI**
   - Install from [CodeQL CLI](https://codeql.github.com/docs/codeql-cli/).
   - Ensure `codeql` is on your PATH, or set `CODEQL_HOME` in `.env` (e.g. `CODEQL_HOME=/opt/codeql`).

2. **Build environment**
   - The library’s normal build dependencies (e.g. autotools, CMake, Meson, compilers, Python) must be installed so the project can build on its own.

3. **Optional: LLM**
   - For better extraction of build steps from README/INSTALL and for LLM-assisted fix suggestions on build failure, configure an LLM in `.env` (e.g. `OPENAI_API_KEY`, `LLM_PROVIDER=openai` or `ollama`).

## Command

```bash
futagassist build --repo <PATH> [--output <DB_PATH>] [--language <LANG>] [--overwrite] [--install-prefix <PATH>] [--build-script <PATH>] [--log-file <PATH>] [-v|--verbose]
```

| Option      | Description |
|------------|-------------|
| `--repo`   | **(Required)** Path to the library source (clone root). |
| `--output` | Where to create the CodeQL database. Default: `<repo>/codeql-db`. |
| `--language` | CodeQL language: `cpp`, `c`, or `python`. Default: `cpp`. |
| `--overwrite` | If the database path already exists, pass CodeQL’s `--overwrite` to replace it. |
| `--install-prefix` | Install the library to this directory for the **linking stage** (adds `--prefix` and `make`/`ninja` install). Default: `<repo>/install`. Override to use a different path. |
| `--build-script` | Use this script as the build command with CodeQL (run from repo root; **overrides** auto-extracted build). Path relative to `--repo` if not absolute. The script should be executable (`chmod +x`). |
| `--log-file` | Write the build-stage log to this file. Default: `<repo>/futagassist-build.log`. |
| `--verbose` / `-v` | Verbose build log (DEBUG level): full LLM prompts and responses, CodeQL command, etc. |

## What happens

1. **Build command**
   - If you pass **`--build-script <PATH>`**, that script is run with CodeQL (from the repo root). Path is resolved relative to `--repo` if not absolute. The script should be executable; no README extraction is used.
   - Otherwise, FutagAssist extracts the build command from README, INSTALL, BUILD, etc. (or file-based detection: `configure.ac`, `meson.build`, `CMakeLists.txt`). If an LLM is configured, it can infer a single build command; otherwise heuristics are used.

2. **CodeQL database creation**
   - The inferred command is run under CodeQL:
     - `codeql database create <output> --language <lang> --command="<build-command>" --source-root <repo>`
   - The build runs from the repo root; the database is written to `--output` (or `<repo>/codeql-db`).

3. **Failure handling**
   - If the build fails and an LLM is configured, FutagAssist can ask for a single fix command (e.g. install a package), run it, and retry the build (up to 3 times).
   - If all retries fail or no LLM is configured, the command exits with an error and the last build log is shown.

4. **Install prefix (for linking stage)**
   - The library is **always installed** to a directory so a future **linking stage** (e.g. compiling fuzz targets) can link against it. By default that directory is **`<repo>/install`**. The build command is extended accordingly: autotools use `./configure --prefix=<DIR>`, CMake uses `-DCMAKE_INSTALL_PREFIX=<DIR>`, Meson uses `--prefix=<DIR>`, and the build runs `make install` or `ninja -C build install` after the build. Use `--install-prefix <DIR>` to override the default and install to a different path.

5. **Build log**
   - A build-stage log is written to `<repo>/futagassist-build.log` (or `--log-file`) for every run.
   - The log includes: stage start/params, README analysis (docs gathered, LLM vs heuristic, extracted build command), CodeQL build attempts, full build command, error output on failure, LLM fix prompt and response (and whether a fix was run), and stage result (success/failed).
   - Use `--verbose` to include full LLM prompts/responses and the exact CodeQL command at DEBUG level.

## Examples

**Build a library already on disk (default C++ database in repo):**

```bash
futagassist build --repo /home/user/repos/zlib
# Database: /home/user/repos/zlib/codeql-db
```

**Build and put the database in a custom location:**

```bash
futagassist build --repo libs/curl --output ./databases/curl-db --language c
```

**Use a custom build script (run with CodeQL from repo root):**

```bash
# Script path relative to --repo
futagassist build --repo libs/mylib --build-script build.sh

# Absolute path
futagassist build --repo libs/mylib --build-script /path/to/my-build.sh
```

**Using downloaded projects (e.g. from `config/libs_projects.yaml`):**

```bash
# Download one project
python scripts/download_projects.py --project zlib

# Build with CodeQL (C)
futagassist build --repo libs/zlib --language c

# Build another (C++)
futagassist build --repo libs/re2 --language cpp
```

## When does FutagAssist ask the LLM for fix suggestions?

FutagAssist **only** asks an LLM for fix suggestions when:

1. An **LLM provider is registered** (e.g. via a plugin in `plugins/llm/` such as `openai_provider.py`).
2. **LLM is configured** in `.env` (e.g. `OPENAI_API_KEY`, `LLM_PROVIDER=openai` or `ollama`).

Check with `futagassist plugins list`: if **Llm Providers** shows `(none)`, no LLM is used and no fix suggestions are attempted. Add and configure an LLM plugin, then re-run the build.

On failure without an LLM, FutagAssist prints the build output and a hint that you can configure an LLM for automatic fix suggestions.

When a build fails, the CLI prints:
- **Build command** — the command that was run (or the wrapper script path).
- **Error output** — CodeQL/build stderr and stdout.
- **LLM suggestion** — if an LLM is configured, the suggested fix command (or “none” if no fix was suggested).

## Troubleshooting

- **“CodeQL binary not found”**  
  Install the CodeQL CLI and ensure `codeql` is on PATH, or set `CODEQL_HOME` in `.env` (FutagAssist will use `$CODEQL_HOME/bin/codeql`).

- **“Runner failed to start 'cd': No such file or directory”**  
  CodeQL’s runner splits the build command by spaces and tries to exec the first token; `cd` is a shell built-in, not an executable. FutagAssist avoids this by writing the build command to a temporary script and passing that script path as `--command`, so the runner executes one executable (the script). If you still see this, ensure you are on a recent FutagAssist version.

- **Build fails but the output is vague (e.g. only “A fatal error occurred”)**  
  CodeQL sometimes summarizes the inner build output. To see the real compiler/build errors, run the same build command yourself from the repo root, e.g.:
  `cd libs/jsoncpp && mkdir -p build && cd build && cmake .. && make`. Fix any missing deps or errors, then run `futagassist build` again.

- **Build fails with missing dependencies**  
  Install the project’s build deps (e.g. `apt install build-essential cmake libssl-dev`). If an LLM is configured (see above), FutagAssist may suggest and run a fix command; otherwise fix the environment and re-run.

- **Wrong build command inferred**  
  The heuristic can be wrong. With an LLM, extraction is usually better. You can also build the project once manually, then run CodeQL yourself:
  `codeql database create <db-path> --language=<lang> --command="<exact-build-cmd>" --source-root=<repo>`.

- **Language choice**  
  Use `--language c` for C-only projects and `--language cpp` for C++ (or mixed C/C++) so CodeQL uses the right extractor.

## Next steps

After a database is created:

- **Analyze** it (when the analyze stage is implemented) to extract function info for fuzz-target generation.
- Use the **CodeQL CLI** directly, e.g. `codeql database analyze <db-path> <query-pack>`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline (build → analyze → generate → compile → fuzz → report).
