# Building a library with CodeQL using FutagAssist

This guide explains how to use FutagAssist to build a C, C++, or Python library and produce a **CodeQL database** for later analysis and fuzz-target generation.

## Prerequisites

1. **CodeQL CLI (bundle required)**
   - You **must** use the **CodeQL bundle** (not the standalone CLI). The bundle includes the CLI **and** language packs (e.g. `codeql/cpp-all`) required for `futagassist analyze`.
   - See [Installing the CodeQL Bundle](#installing-the-codeql-bundle) below for step-by-step instructions.

2. **Build environment**
   - The library’s normal build dependencies (e.g. autotools, CMake, Meson, compilers, Python) must be installed so the project can build on its own.

3. **Optional: LLM**
   - For better extraction of build steps from README/INSTALL and for LLM-assisted fix suggestions on build failure, configure an LLM in `.env` (e.g. `OPENAI_API_KEY`, `LLM_PROVIDER=openai` or `ollama`).

## Installing the CodeQL Bundle

FutagAssist requires the **CodeQL bundle** (not the standalone CLI) because the bundle includes language packs like `codeql/cpp-all` that provide the `cpp` module for analysis.

### Step 1: Download the bundle

Go to the [CodeQL Action releases](https://github.com/github/codeql-action/releases) and download the **bundle** for your platform:

| Platform | Asset name |
|----------|------------|
| Linux (x64) | `codeql-bundle-linux64.tar.zst` or `.tar.gz` |
| macOS (x64) | `codeql-bundle-osx64.tar.zst` or `.tar.gz` |
| Windows | `codeql-bundle-win64.zip` |

**Important:** Download from a `codeql-bundle-vX.Y.Z` tag (e.g. `codeql-bundle-v2.20.0`), **not** the CodeQL Action release (v3.x / v4.x).

### Step 2: Extract the bundle

```bash
# Linux example (using zstd for .tar.zst, or tar for .tar.gz)
mkdir -p ~/codeql
cd ~/codeql
tar --zstd -xf ~/Downloads/codeql-bundle-linux64.tar.zst
# Or for .tar.gz:
# tar -xzf ~/Downloads/codeql-bundle-linux64.tar.gz
```

After extraction, you should have:

```
~/codeql/
├── codeql              # The CodeQL CLI binary
├── qlpacks/            # Language packs
│   └── codeql/
│       ├── cpp-all/    # C/C++ pack (with version subdirectory, e.g. 7.0.0/)
│       ├── cpp-queries/
│       ├── java-all/
│       └── ...
└── ...
```

### Step 3: Set environment variables

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
export CODEQL_HOME=~/codeql
export PATH="$CODEQL_HOME:$PATH"
```

Then reload:

```bash
source ~/.bashrc  # or ~/.zshrc
```

### Step 4: Verify the installation

```bash
# Check CLI version
codeql version

# Check that packs are found (should list codeql/cpp-all, codeql/cpp-queries, etc.)
codeql resolve packs

# Verify the cpp pack exists
ls -la $CODEQL_HOME/qlpacks/codeql/cpp-all/
```

If `codeql resolve packs` shows the `codeql/cpp-all` pack, the installation is correct.

### Troubleshooting installation

| Problem | Solution |
|---------|----------|
| `codeql: command not found` | Ensure `$CODEQL_HOME` is set and `$CODEQL_HOME` is in `$PATH`. |
| `codeql resolve packs` shows no packs | You may have the standalone CLI, not the bundle. Download the **bundle** from [codeql-bundle releases](https://github.com/github/codeql-action/releases). |
| `could not resolve module cpp` during analyze | The `codeql/cpp-all` pack is missing. Verify `$CODEQL_HOME/qlpacks/codeql/cpp-all/` exists. |
| Packs are in a different location | Set `CODEQL_HOME` to the directory that contains both the `codeql` binary and the `qlpacks/` folder. |

## Command

```bash
futagassist build --repo <PATH> [--output <DB_PATH>] [--language <LANG>] [--overwrite] [--build-script <PATH>] [--configure-options <FLAGS>] [--log-file <PATH>] [--no-interactive] [-v|--verbose]
```

| Option      | Description |
|------------|-------------|
| `--repo`   | **(Required)** Path to the library source (clone root). |
| `--output` | Where to create the CodeQL database. Default: `<repo>/codeql-db`. |
| `--language` | CodeQL language: `cpp`, `c`, or `python`. Default: `cpp`. |
| `--overwrite` | If the database path already exists, pass CodeQL’s `--overwrite` to replace it. |
| `--build-script` | Use this script as the build command with CodeQL (run from repo root; **overrides** auto-extracted build). Path relative to `--repo` if not absolute. The script should be executable (`chmod +x`). |
| `--configure-options` | Extra flags for the **configure** step (e.g. `--without-ssl`, `--with-openssl`). Appended to the detected `./configure` command only. Ignored when using `--build-script`. Useful for projects that require a TLS backend or other configure choices (e.g. curl). |
| `--log-file` | Write the build-stage log to this file. Default: `<repo>/futagassist-build.log`. |
| `--no-interactive` | Never prompt; on failure with a suggested fix, print and exit without asking to run it (e.g. for CI). |
| `--verbose` / `-v` | Verbose build log (DEBUG level): full LLM prompts and responses, CodeQL command, etc. |

## What happens

1. **Build command**
   - If you pass **`--build-script <PATH>`**, that script is run with CodeQL (from the repo root). Path is resolved relative to `--repo` if not absolute. The script should be executable; no README extraction is used.
   - Otherwise, FutagAssist extracts the build command from README, INSTALL, BUILD, etc. (or file-based detection: `configure.ac`, `meson.build`, `CMakeLists.txt`). If an LLM is configured, it can infer a single build command; otherwise heuristics are used.

2. **CodeQL database creation**
   - The inferred command is run under CodeQL:
     - `codeql database create <output> --language <lang> --command="<build-command>" --source-root <repo>`
   - The build runs from the repo root; the database is written to `--output` (or `<repo>/codeql-db`).
   - **`--overwrite`** replaces the CodeQL database directory and runs a **clean step** before building: FutagAssist infers a clean command from the build system (e.g. `make clean` for autotools, `ninja -C build -t clean` for Meson, `cmake --build build --target clean` for CMake) and runs it from the repo root. If the clean step fails (e.g. no Makefile yet), the build continues anyway. When using **`--build-script`**, no clean step is run.

3. **Failure handling**
   - If the build fails and an LLM is configured, FutagAssist asks for a single fix command (e.g. install a package) and prints it. In **interactive** mode (stdin is a TTY and you did not pass `--no-interactive`), the CLI first prompts: *Add configure options for retry? (e.g. --without-ssl) [leave empty to skip]:* — you can type extra configure flags (e.g. `--without-ssl` for curl) and FutagAssist will retry the build with those options appended to the configure step. If you leave it empty, it then may prompt: *Run this fix and retry build? [y/N]* for the LLM-suggested fix. If you answer yes, it runs the fix command in the repo root and retries the build once. If you answer no, or if you use `--no-interactive` (e.g. in CI), it exits with an error and the last build log is shown; you can run the suggested command manually and re-run `futagassist build`.
   - If all retries fail or no LLM is configured, the command exits with an error and the last build log is shown.

4. **Build log**
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

**Projects that require configure flags (e.g. curl — select TLS backend or disable TLS):**

```bash
# Disable TLS (minimal deps)
futagassist build --repo libs/curl --configure-options "--without-ssl"

# Or use OpenSSL
futagassist build --repo libs/curl --configure-options "--with-openssl"
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
- **LLM suggestion** — if an LLM is configured, the suggested fix command is shown as "Suggested fix (run manually if you agree): …"; FutagAssist does not run it. Or “no suggestion line is printed” if the LLM had no fix; or **“request failed (&lt;error&gt;)”** if the LLM API call failed (e.g. `Connection error`). In that case, check your API key, network, proxy, and `OPENAI_BASE_URL` (or LLM config) in `.env`; the build log (`futagassist-build.log`) also records `LLM fix request failed: <error>`.

## Troubleshooting

- **“CodeQL binary not found”**  
  Install the CodeQL CLI and ensure `codeql` is on PATH, or set `CODEQL_HOME` in `.env` (FutagAssist will use `$CODEQL_HOME/bin/codeql`).

- **“Runner failed to start 'cd': No such file or directory”**  
  CodeQL’s runner splits the build command by spaces and tries to exec the first token; `cd` is a shell built-in, not an executable. FutagAssist avoids this by writing the build command to a temporary script and passing that script path as `--command`, so the runner executes one executable (the script). If you still see this, ensure you are on a recent FutagAssist version.

- **Build fails but the output is vague (e.g. only “A fatal error occurred”)**  
  CodeQL sometimes summarizes the inner build output. To see the real compiler/build errors, run the same build command yourself from the repo root, e.g.:
  `cd libs/jsoncpp && mkdir -p build && cd build && cmake .. && make`. Fix any missing deps or errors, then run `futagassist build` again.

- **Build fails with missing dependencies**  
  Install the project’s build deps (e.g. `apt install build-essential cmake libssl-dev`). If an LLM is configured (see above), FutagAssist may suggest a fix command for you to run manually; otherwise fix the environment and re-run.

- **“LT_PATH_LD: command not found” or “ltmain.sh not found” (autotools)**  
  The project uses autotools and the build system needs to be **regenerated** with your system’s libtool/autoconf. Installing `libtool autoconf automake` is not enough. From the repo root run: `libtoolize && autoreconf -fi`, then run `futagassist build` again. (Some projects' `autogen.sh` refuses to run on "partial" trees; prefer `libtoolize && autoreconf -fi` for that case.)

- **“configure: error: select TLS backend(s) or disable TLS with --without-ssl” (curl)**  
  Curl’s configure requires a TLS backend or `--without-ssl`. Run with extra configure options: `futagassist build --repo libs/curl --configure-options "--without-ssl"` or `--configure-options "--with-openssl"`. In interactive mode, when the build fails, you can type `--without-ssl` at the “Add configure options for retry?” prompt and FutagAssist will retry with that.

- **Wrong build command inferred**  
  The heuristic can be wrong. With an LLM, extraction is usually better. You can also build the project once manually, then run CodeQL yourself:
  `codeql database create <db-path> --language=<lang> --command="<exact-build-cmd>" --source-root=<repo>`.

- **Language choice**  
  Use `--language c` for C-only projects and `--language cpp` for C++ (or mixed C/C++) so CodeQL uses the right extractor.

- **“LLM suggestion: request failed (Connection error)”**  
  The LLM is configured but the API call failed (network unreachable, wrong base URL, proxy, or invalid key). Check `.env`: `OPENAI_API_KEY`, `OPENAI_BASE_URL` (if using a proxy or custom endpoint), and `LLM_PROVIDER`. Run `futagassist check` to verify the LLM is reachable. The build log at `<repo>/futagassist-build.log` shows the exact error (e.g. `LLM fix request failed: Connection error`).

## Next steps

After a database is created:

- **Analyze** it with `futagassist analyze --db <path>` to extract function info for fuzz-target generation. An LLM (if configured) can suggest additional usage contexts for fuzz targets; see [ANALYZE_STAGE.md](ANALYZE_STAGE.md).
- Use the **CodeQL CLI** directly, e.g. `codeql database analyze <db-path> <query-pack>`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline (build → analyze → generate → compile → fuzz → report). The build stage does not install the library; a future **Fuzz Build** stage will build and install an instrumented library (debug + sanitizers) for fuzzing; see [FUZZ_BUILD_STAGE.md](FUZZ_BUILD_STAGE.md).
