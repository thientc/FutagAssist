# Analysis stage (Phase 3)

This guide describes the **Analysis** pipeline stage: extracting function information and **usage contexts** (ordered function-call sequences) from a CodeQL database using a `LanguageAnalyzer` plugin and optionally exporting results as JSON.

## Overview

- **Stage:** `AnalyzeStage` (`analyze`)
- **Input:** CodeQL database path (from the [build stage](BUILD_WITH_CODEQL.md))
- **Output:**
  - **Functions:** List of `FunctionInfo` (name, signature, return type, parameters, file path, line, includes, context).
  - **Usage contexts:** List of `UsageContext` — ordered sequences of function calls (e.g. `["init", "process", "cleanup"]`) observed in the codebase. These contexts are very useful for generating fuzz targets that exercise realistic call orders.
- **Delegation:** Function extraction and usage-context extraction are delegated to a **LanguageAnalyzer** plugin for the chosen language (e.g. C/C++, Python). A **context builder** enriches each function with surrounding source lines when a repo path is available. Results can be written via a **Reporter** (e.g. JSON).

## Prerequisites

1. **CodeQL database**
   - Create one with `futagassist build --repo <path>` (see [BUILD_WITH_CODEQL.md](BUILD_WITH_CODEQL.md)).

2. **Language analyzer**
   - A **LanguageAnalyzer** must be registered for your language (e.g. `cpp`, `c`, `python`). A **C++ analyzer** is provided in `plugins/cpp/cpp_analyzer.py`; run `futagassist analyze` from the project root (where `plugins/` exists) so it is loaded. For other languages, add a plugin that calls `registry.register_language("<lang>", YourAnalyzer)`.
   - Run `futagassist plugins list` to see registered **Language analyzers**.

3. **Optional: LLM**
   - For extra usage context suggestions, configure an LLM (same as build: `OPENAI_API_KEY` / `LLM_PROVIDER` in `.env`). See [LLM_PLUGINS.md](LLM_PLUGINS.md) or the build doc. When configured, the analyze stage may ask the LLM to suggest additional usage contexts after LanguageAnalyzer extraction.

4. **Optional: JSON output**
   - The built-in **JSON** reporter is registered by default. Use `--output <path>` to write a single JSON file containing both `functions` and `usage_contexts`.

## Command

```bash
futagassist analyze --db <PATH> [--output <JSON_PATH>] [--language <LANG>]
```

| Option       | Description |
|-------------|-------------|
| `--db`      | **(Required)** Path to the CodeQL database (from the build stage). |
| `--output`  | Write functions and usage contexts to this JSON file. If omitted, only the count is printed. |
| `--language`| Language for analysis (must match a registered LanguageAnalyzer). Default: `cpp`. |

## What happens

1. **Resolve database and language**
   - The stage checks that `--db` exists and that a LanguageAnalyzer is registered for `--language`. If not, it exits with an error (e.g. *No language analyzer registered for 'cpp'*).

2. **Function and usage-context extraction**
   - The stage gets the LanguageAnalyzer for the given language and calls:
     - `analyzer.extract_functions(db_path)` — returns a list of `FunctionInfo`.
     - `analyzer.extract_usage_contexts(db_path)` — returns a list of `UsageContext` (ordered function-call sequences). Each `UsageContext` has `name`, `calls` (list of function names in order), optional `source_file`, `source_line`, and `description`. These sequences represent typical or observed usage patterns (e.g. init → use → cleanup) and are very useful for generating fuzz targets that call functions in a realistic order.

3. **Context enrichment**
   - If a repo path is available (e.g. when the stage is run as part of a pipeline with `repo_path` set), a **context builder** enriches each function with surrounding source lines (`FunctionInfo.context`) for use in later harness generation.

4. **JSON export**
   - If `--output` is set and the **json** reporter is registered, the stage writes a single JSON file with two top-level keys: `"functions"` (array of function objects) and `"usage_contexts"` (array of usage-context objects). Each usage context object has `name`, `calls`, `source_file`, `source_line`, and `description`.

5. **Result**
   - The stage returns success and puts `functions` in `result.data["functions"]` and `usage_contexts` in `result.data["usage_contexts"]`. The pipeline context is updated so later stages (e.g. Generation) can use both. The CLI prints *Analyzed N function(s).* and, if `--output` was used, *Wrote &lt;path&gt;*.

## CodeQL runner and context builder

- **CodeQL runner** (`src/futagassist/analysis/codeql_runner.py`): Utility to run CodeQL queries against a database (`codeql database run-queries`). Language analyzers can use it to run `.ql` files and parse results into `FunctionInfo`.
- **Context builder** (`src/futagassist/analysis/context_builder.py`): `enrich_functions(functions, repo_path, ...)` fills `FunctionInfo.context` with source lines around each function’s `file_path` and `line` (configurable `before_lines` / `after_lines`).

## CodeQL queries for C/C++

The C++ analyzer includes several CodeQL queries in `plugins/cpp/` for extracting function information:

| Query | Description |
|-------|-------------|
| `list_functions.ql` | **Main query.** Extracts all functions with details: file path, line, name, qualified name, return type, parameters, and whether public (header-declared or external linkage). |
| `api_functions.ql` | Identifies **public API functions** suitable for fuzzing. Scores functions based on: header declaration, external linkage, pointer parameters, size parameters, and input-processing names. |
| `fuzz_targets.ql` | Finds **ideal fuzz target candidates**: functions that take (buffer, size) pairs, C strings, or file handles. Prioritizes input-processing functions (parse, read, decode, etc.). |
| `parameter_semantics.ql` | Classifies each **parameter by semantic role** (FILE_PATH, FILE_HANDLE, URL, CALLBACK, USERDATA, OUTPUT_BUFFER, etc.) from name and type. Used to attach `parameter_semantics` to `FunctionInfo`; the generate stage uses this to emit temp-file or nullptr code. |
| `function_calls.ql` | Extracts **caller → callee relationships** to understand call graphs and build usage contexts (init → process → cleanup sequences). |
| `init_cleanup_pairs.ql` | Identifies **init/cleanup function pairs** (e.g. `open`/`close`, `alloc`/`free`, `create`/`destroy`) that should be called together in fuzz harnesses. |
| `includes.ql` | Extracts **#include directives** per source file for generating complete fuzz harnesses with proper headers. |
| `function_details.ql` | Detailed function info including static/inline/virtual qualifiers. |

### Fuzz target scoring

The `fuzz_targets.ql` query assigns a **fuzz score** to each function:

| Criterion | Score |
|-----------|-------|
| Takes (buffer, size) pair | +10 |
| Takes C string | +5 |
| Input-processing name (parse, read, decode...) | +5 |
| Public API (declared in header) | +3 |
| Non-static | +2 |

Functions with score ≥ 5 are returned, sorted by score descending.

### Parameter semantics

The `parameter_semantics.ql` query assigns a **semantic role** to each function parameter (one per parameter, in order). Roles are used by the generate stage to produce appropriate harness code:

| Role | Description | Harness behavior |
|------|-------------|------------------|
| FILE_PATH | Filename/path parameter (e.g. `filename`, `path`) | Create temp file from fuzz input, pass path; optional unlink. |
| FILE_HANDLE | File handle (e.g. `FILE*`, `int fd`) | Create temp file, open handle, pass to function; `fclose` after call. |
| CONFIG_PATH, URL | Config path or URL parameter | Treated like FILE_PATH (temp file, pass path). |
| CALLBACK, USERDATA | Callback or userdata pointer | Pass `nullptr` (or TODO). |
| OUTPUT_BUFFER, INOUT_BUFFER | Output/inout buffer | Type-based consumption. |
| UNKNOWN | No semantic match | Type-based consumption. |

`FunctionInfo.parameter_semantics` is a list of strings, one per parameter, aligned with `FunctionInfo.parameters`.

### API function scoring

The `api_functions.ql` query assigns an **API score**:

| Criterion | Score |
|-----------|-------|
| Declared in header | +3 |
| External linkage | +2 |
| Takes pointer parameter | +2 |
| Takes size parameter | +1 |
| Input-processing name | +2 |


## CodeQL bundle (required)

The C++ analyzer runs a CodeQL query that `import cpp`. This requires the **CodeQL bundle** (not the standalone CLI), which includes language packs like `codeql/cpp-all`.

**For installation instructions, see [BUILD_WITH_CODEQL.md - Installing the CodeQL Bundle](BUILD_WITH_CODEQL.md#installing-the-codeql-bundle).**

### Quick verification

After installing the bundle, verify with:

```bash
# Check that packs are found
codeql resolve packs | grep cpp-all

# Check the pack directory exists
ls -la $CODEQL_HOME/qlpacks/codeql/cpp-all/
```

### Troubleshooting "could not resolve module cpp"

This error means CodeQL cannot find the `codeql/cpp-all` language pack. Common causes:

| Cause | Solution |
|-------|----------|
| Using standalone CLI instead of bundle | Download the **bundle** from [codeql-bundle releases](https://github.com/github/codeql-action/releases) (tags like `codeql-bundle-v2.20.0`). |
| `CODEQL_HOME` not set or wrong | Set `CODEQL_HOME` to the directory containing both the `codeql` binary and the `qlpacks/` folder. |
| Packs not extracted correctly | Verify `$CODEQL_HOME/qlpacks/codeql/cpp-all/` exists with `ls`. |

Run `codeql resolve packs` to see if CodeQL can find its packs. If it shows nothing, the bundle is not installed correctly.

## Optional: LLM-assisted usage context suggestion

When an LLM is configured (same as build: `OPENAI_API_KEY` / `LLM_PROVIDER` in `.env`), the analyze stage may call it **after** LanguageAnalyzer extraction:

- The LLM is given the list of functions (names/signatures) and existing usage contexts and can suggest **additional** ordered call sequences (usage contexts) useful for fuzzing (e.g. init → use → cleanup, parse then process).
- Failures are non-fatal: if the LLM is unavailable or returns invalid output, the stage still succeeds with analyzer-only results.
- This uses the same LLM as the build stage (README extraction and fix suggestions), so one config covers both stages.

## Examples

```bash
# Analyze a database, print count only
futagassist analyze --db ./libs/mylib/codeql-db

# Analyze and write function list to JSON
futagassist analyze --db ./libs/mylib/codeql-db --output ./out/functions.json

# Use a specific language (must be registered)
futagassist analyze --db ./codeql-db --language cpp --output functions.json
```

## Usage contexts for fuzz target generation

**Usage contexts** are ordered sequences of function calls (e.g. `["init", "process", "cleanup"]`) extracted from the codebase. They capture typical or observed call orders and are very useful for generating fuzz targets:

- A fuzz target can be generated for a **single function** (as before) or for a **sequence** of calls from a usage context.
- Sequences help ensure setup/teardown (e.g. open → read → close) and realistic API usage, improving coverage and bug finding.

Language analyzers implement `extract_usage_contexts(db_path)` to return such sequences (e.g. from CodeQL call-graph or control-flow queries, or from heuristics over call sites).

## Pipeline integration

When running the full pipeline (e.g. `futagassist run --repo <path>`), the analyze stage runs after the build stage. The build stage sets `context.db_path`; the analyze stage reads it and sets `context.functions` and `context.usage_contexts`. If you run `futagassist analyze` standalone, you must pass `--db`; `repo_path` is optional (used only for function context enrichment).

## Next steps

- Use the function list and usage contexts (or the JSON file) in the **Generation** stage to produce fuzz targets (Phase 4), including targets that exercise call sequences from usage contexts.
- See [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline (build → analyze → generate → compile → fuzz → report).
