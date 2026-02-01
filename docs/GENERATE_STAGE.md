# Generation Stage (Phase 4)

This guide describes the **Generation** pipeline stage: creating fuzz harnesses from analyzed function information using LLM assistance and/or templates.

## Overview

- **Stage:** `GenerateStage` (`generate`)
- **Input:** Function list from the [analyze stage](ANALYZE_STAGE.md)
- **Output:**
  - **Generated harnesses:** List of `GeneratedHarness` objects with source code
  - **Harness files:** `.cpp` files written to the output directory

## Prerequisites

1. **Functions JSON file**
   - Run `futagassist analyze --db <db> --output functions.json` first

2. **Optional: LLM**
   - For high-quality, context-aware harnesses, configure an LLM (`.env` with `OPENAI_API_KEY` and `LLM_PROVIDER=openai`)
   - Without LLM, template-based harnesses with TODO comments are generated

3. **Optional: Compiler**
   - `clang++` for full syntax validation (basic structural checks work without it)

## Command

```bash
futagassist generate --functions <JSON_PATH> [--output <DIR>] [--max-targets <N>] [--no-llm] [--no-validate]
```

| Option | Description |
|--------|-------------|
| `--functions` | **(Required)** Path to functions JSON file from analyze stage |
| `--output` | Output directory for generated harnesses (default: `./fuzz_targets`) |
| `--max-targets` | Maximum number of harnesses to generate |
| `--no-llm` | Use template-based generation only (no LLM) |
| `--no-validate` | Skip syntax validation |
| `--language` | Language for harnesses (default: `cpp`) |

## What happens

1. **Load functions**
   - Reads function info and usage contexts from the JSON file

2. **Harness generation**
   - For each function (or usage context), generates a libFuzzer harness:
     - **With LLM:** Prompts the LLM with function signature, parameters, and context to generate a complete harness
     - **Without LLM:** Creates a template with `LLVMFuzzerTestOneInput` and TODO comments

3. **Syntax validation**
   - Validates generated code for:
     - Presence of `LLVMFuzzerTestOneInput` entry point
     - Balanced braces and parentheses
     - `#include` directives
     - Return statement
   - Full validation uses `clang++ -fsyntax-only`

4. **Write harnesses**
   - Writes valid harnesses to the output directory as `.cpp` files
   - Filenames: `harness_<function_name>.cpp`

## LLM Prompts

The generator uses these prompts for LLM-based generation:

**Single function:**
```
Generate a libFuzzer harness for the following C/C++ function.

Function signature: {signature}
File: {file_path}
Return type: {return_type}
Parameters: {parameters}

Context (surrounding code):
{context}

Requirements:
1. Use the standard libFuzzer entry point
2. Parse the fuzz input to create valid arguments
3. Handle edge cases (null checks, size validation)
4. Return 0 at the end
5. Include necessary headers

Generate ONLY the complete C/C++ source code.
```

**Call sequence:**
```
Generate a libFuzzer harness that calls the following sequence of functions.

Call sequence: {calls}
Function signatures: {signatures}

Requirements:
1. Call functions in the specified order
2. Handle initialization and cleanup properly
3. Parse the fuzz input to create valid arguments
```

## Template-based harnesses with FuzzedDataProvider

Without LLM, harnesses use [LLVM's FuzzedDataProvider](https://github.com/llvm/llvm-project/blob/main/compiler-rt/include/fuzzer/FuzzedDataProvider.h) for intelligent parameter generation:

```cpp
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <vector>
#include <string>
#include <fuzzer/FuzzedDataProvider.h>
{includes}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    FuzzedDataProvider fdp(data, size);
    // Fuzz harness for {function_name}
    // Signature: {signature}
    
    if (size < 1) return 0;
    
    // Parameters are consumed using FuzzedDataProvider methods
    int param1 = fdp.ConsumeIntegral<int>();
    size_t len = fdp.ConsumeIntegralInRange<size_t>(0, fdp.remaining_bytes());
    std::vector<uint8_t> buf_vec = fdp.ConsumeBytes<uint8_t>(len);
    uint8_t* buf = buf_vec.data();
    
    {function_name}(param1, buf, len);
    return 0;
}
```

### Parameter Type Mapping

| C/C++ Type | FuzzedDataProvider Method |
|------------|--------------------------|
| `int`, `size_t`, `uint32_t`, etc. | `ConsumeIntegral<T>()` |
| `float`, `double` | `ConsumeFloatingPoint<T>()` |
| `bool` | `ConsumeBool()` |
| `const char*` | `ConsumeRandomLengthString()` + `.c_str()` |
| `char*` (mutable) | `ConsumeRandomLengthString()` + copy to vector |
| `uint8_t*`, `void*` (buffer) | `ConsumeBytes<uint8_t>(size)` |
| Buffer + size pair | Size first, then `ConsumeBytes(size)` |
| Custom pointers | `nullptr` with TODO comment |

### Buffer+Size Detection

The generator automatically detects buffer+size parameter pairs:

```cpp
// Function: void process(uint8_t* data, size_t data_len)
size_t data_len = fdp.ConsumeIntegralInRange<size_t>(0, fdp.remaining_bytes());
std::vector<uint8_t> data_vec = fdp.ConsumeBytes<uint8_t>(data_len);
uint8_t* data = data_vec.data();
process(data, data_len);
```

Size parameter detection patterns: `*_len`, `*_size`, `*_length`, `*_count`, `len`, `size`, `n`, `num*`, `cb*`

## Compile flags

Generated harnesses include default compile flags for libFuzzer:

```
-g -O1 -fno-omit-frame-pointer -fsanitize=fuzzer,address -fsanitize-address-use-after-scope
```

## Examples

```bash
# Generate with LLM (requires LLM configured in .env)
futagassist generate --functions ./output/functions.json --output ./fuzz_targets

# Generate without LLM (template-based)
futagassist generate --functions ./output/functions.json --no-llm

# Generate only 5 targets
futagassist generate --functions ./output/functions.json --max-targets 5

# Skip validation (faster)
futagassist generate --functions ./output/functions.json --no-validate
```

## Output structure

```
fuzz_targets/
├── harness_png_read_image.cpp
├── harness_png_write_png.cpp
├── harness_png_create_read_struct.cpp
└── harness_seq_init_read_cleanup.cpp   # sequence harness
```

## Harness validation

The `SyntaxValidator` checks:

| Check | Description |
|-------|-------------|
| Entry point | `LLVMFuzzerTestOneInput` present |
| Includes | At least one `#include` directive |
| Return | Has `return` statement |
| Braces | Balanced `{` and `}` |
| Parentheses | Balanced `(` and `)` |

Full validation (with `clang++`) catches:
- Syntax errors
- Missing declarations
- Type errors

## Pipeline integration

When running the full pipeline:

```bash
futagassist run --repo /path/to/library
```

The generate stage runs after analyze, receiving `context.functions` and `context.usage_contexts`. Generated harnesses are stored in `context.generated_harnesses` and written to `context.fuzz_targets_dir`.

## Next steps

- **Compile** the generated harnesses with `futagassist compile` *(coming soon)*
- **Fuzz** the compiled binaries with `futagassist fuzz` *(coming soon)*
- See [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline
