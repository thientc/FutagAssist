"""Harness generator: creates fuzz harnesses using templates and LLM."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from futagassist.core.schema import FunctionInfo, GeneratedHarness, UsageContext
from futagassist.generation.param_analyzer import (
    ParsedParam,
    ParamKind,
    find_buffer_size_pairs,
    generate_fdp_consume,
    parse_parameter,
)

if TYPE_CHECKING:
    from futagassist.protocols.llm_provider import LLMProvider

log = logging.getLogger(__name__)


# C/C++ libFuzzer harness template with FuzzedDataProvider
CPP_HARNESS_TEMPLATE = '''#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <vector>
#include <string>
#include <fuzzer/FuzzedDataProvider.h>
{includes}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {{
    FuzzedDataProvider fdp(data, size);
{body}
    return 0;
}}
'''

# Simpler template for basic cases (no FuzzedDataProvider)
CPP_HARNESS_SIMPLE_TEMPLATE = '''#include <stdint.h>
#include <stddef.h>
#include <string.h>
{includes}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {{
{body}
    return 0;
}}
'''

# Prompt template for LLM-based harness generation
LLM_HARNESS_PROMPT = '''Generate a libFuzzer harness for the following C/C++ function.

Function signature:
{signature}

File: {file_path}
Return type: {return_type}
Parameters: {parameters}

Context (surrounding code):
{context}

Requirements:
1. Use the standard libFuzzer entry point: extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
2. Use FuzzedDataProvider to parse the fuzz input into typed arguments:
   - Include <fuzzer/FuzzedDataProvider.h>
   - Create: FuzzedDataProvider fdp(data, size);
   - Use: fdp.ConsumeIntegral<T>(), fdp.ConsumeBytes<uint8_t>(n), fdp.ConsumeRandomLengthString(), fdp.ConsumeBool(), etc.
3. For buffer+size parameter pairs, consume size first, then consume that many bytes
4. Handle edge cases (null checks, size validation, early return if fdp.remaining_bytes() < minimum)
5. Return 0 at the end
6. Include necessary headers

Generate ONLY the complete C/C++ source code for the harness, no explanations.
'''

LLM_SEQUENCE_PROMPT = '''Generate a libFuzzer harness that calls the following sequence of functions.

Call sequence: {calls}

Function signatures:
{signatures}

Requirements:
1. Use the standard libFuzzer entry point: extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
2. Use FuzzedDataProvider to parse fuzz input:
   - Include <fuzzer/FuzzedDataProvider.h>
   - Create: FuzzedDataProvider fdp(data, size);
3. Call functions in the specified order
4. Handle initialization and cleanup properly (e.g., if first function returns a handle, pass it to subsequent calls, then cleanup)
5. For resource-acquiring functions (open, create, init), ensure matching cleanup (close, destroy, cleanup)
6. Return 0 at the end

Generate ONLY the complete C/C++ source code for the harness, no explanations.
'''


class HarnessGenerator:
    """Generates fuzz harnesses from function info using templates and/or LLM."""

    def __init__(
        self,
        llm: LLMProvider | None = None,
        language: str = "cpp",
        output_dir: Path | None = None,
    ) -> None:
        self._llm = llm
        self._language = language
        self._output_dir = output_dir

    def generate_for_function(
        self,
        func: FunctionInfo,
        use_llm: bool = True,
    ) -> GeneratedHarness:
        """Generate a harness for a single function."""
        if use_llm and self._llm:
            return self._generate_with_llm(func)
        return self._generate_from_template(func)

    def generate_for_sequence(
        self,
        usage_context: UsageContext,
        functions: list[FunctionInfo],
        use_llm: bool = True,
    ) -> GeneratedHarness:
        """Generate a harness for a sequence of function calls."""
        if use_llm and self._llm:
            return self._generate_sequence_with_llm(usage_context, functions)
        return self._generate_sequence_from_template(usage_context, functions)

    def generate_batch(
        self,
        functions: list[FunctionInfo],
        usage_contexts: list[UsageContext] | None = None,
        use_llm: bool = True,
        max_targets: int | None = None,
        ordered_items: list[tuple] | None = None,
        use_subdirs: bool = True,
    ) -> list[GeneratedHarness]:
        """Generate harnesses for multiple functions and/or sequences.

        If ordered_items is provided, each element is (item, category) where item is
        FunctionInfo or UsageContext and category is 'api', 'usage_contexts', or 'other'.
        Otherwise falls back to legacy order: functions first, then usage_contexts.
        """
        harnesses: list[GeneratedHarness] = []
        if usage_contexts is None:
            usage_contexts = []

        if ordered_items:
            for item, category in ordered_items:
                try:
                    if isinstance(item, FunctionInfo):
                        harness = self.generate_for_function(item, use_llm=use_llm)
                    else:
                        harness = self.generate_for_sequence(item, functions, use_llm=use_llm)
                    harness.category = category
                    harnesses.append(harness)
                except Exception as e:
                    name = getattr(item, "name", None) or (getattr(item, "calls", ["?"])[0] if getattr(item, "calls", None) else "?")
                    log.warning("Failed to generate harness for %s: %s", name, e)
                    harnesses.append(
                        GeneratedHarness(
                            function_name=str(name),
                            is_valid=False,
                            validation_errors=[str(e)],
                            category=category,
                        )
                    )
            return harnesses

        # Legacy path: no ordered_items
        remaining = max_targets
        funcs_to_process = functions[:remaining] if remaining else functions
        for func in funcs_to_process:
            try:
                harness = self.generate_for_function(func, use_llm=use_llm)
                harness.category = "other" if use_subdirs else ""
                harnesses.append(harness)
            except Exception as e:
                log.warning("Failed to generate harness for %s: %s", func.name, e)
                harnesses.append(
                    GeneratedHarness(
                        function_name=func.name,
                        is_valid=False,
                        validation_errors=[str(e)],
                        category="other" if use_subdirs else "",
                    )
                )
        if remaining:
            remaining = max(0, remaining - len(funcs_to_process))
        if usage_contexts and (remaining is None or remaining > 0):
            contexts_to_process = usage_contexts[:remaining] if remaining else usage_contexts
            for ctx in contexts_to_process:
                try:
                    harness = self.generate_for_sequence(ctx, functions, use_llm=use_llm)
                    harness.category = "usage_contexts" if use_subdirs else ""
                    harnesses.append(harness)
                except Exception as e:
                    log.warning("Failed to generate harness for sequence %s: %s", ctx.name, e)
        return harnesses

    def _generate_with_llm(self, func: FunctionInfo) -> GeneratedHarness:
        """Generate harness using LLM."""
        if not self._llm:
            raise ValueError("LLM not configured")

        prompt = LLM_HARNESS_PROMPT.format(
            signature=func.signature,
            file_path=func.file_path,
            return_type=func.return_type,
            parameters=", ".join(func.parameters) if func.parameters else "(none)",
            context=func.context or "(no context available)",
        )

        response = self._llm.complete(prompt)
        source_code = self._extract_code(response)
        includes = self._extract_includes(source_code)

        harness = GeneratedHarness(
            function_name=func.name,
            file_path=f"harness_{self._sanitize_name(func.name)}.cpp",
            source_code=source_code,
            includes=includes,
            compile_flags=self._default_compile_flags(),
            link_flags=self._default_link_flags(),
        )

        return harness

    def _generate_from_template(self, func: FunctionInfo) -> GeneratedHarness:
        """Generate harness using template with FuzzedDataProvider."""
        # Build includes
        includes_list = []
        semantics = getattr(func, "parameter_semantics", None) or []
        if any(s in ("FILE_PATH", "FILE_HANDLE", "CONFIG_PATH", "URL") for s in semantics):
            includes_list.append("#include <cstdio>")
            includes_list.append("#include <unistd.h>")
        if func.file_path:
            # Try to include the header for this source file
            header = func.file_path.replace(".c", ".h").replace(".cpp", ".h")
            includes_list.append(f'#include "{header}"')
        # Add any includes from function info
        for inc in func.includes:
            if inc not in includes_list:
                includes_list.append(inc)
        includes_str = "\n".join(includes_list)

        # Parse parameters and build harness body
        parsed_params = [parse_parameter(p) for p in func.parameters]
        body = self._build_fdp_body(func, parsed_params)

        source_code = CPP_HARNESS_TEMPLATE.format(
            includes=includes_str,
            body=body,
        )

        return GeneratedHarness(
            function_name=func.name,
            file_path=f"harness_{self._sanitize_name(func.name)}.cpp",
            source_code=source_code,
            includes=self._extract_includes(source_code),
            compile_flags=self._default_compile_flags(),
            link_flags=self._default_link_flags(),
        )

    def _generate_sequence_with_llm(
        self,
        usage_context: UsageContext,
        functions: list[FunctionInfo],
    ) -> GeneratedHarness:
        """Generate harness for a call sequence using LLM."""
        if not self._llm:
            raise ValueError("LLM not configured")

        # Build function signatures for the sequence
        func_map = {f.name: f for f in functions}
        signatures = []
        for call in usage_context.calls:
            if call in func_map:
                signatures.append(f"- {func_map[call].signature}")
            else:
                signatures.append(f"- {call}(...)")

        prompt = LLM_SEQUENCE_PROMPT.format(
            calls=" -> ".join(usage_context.calls),
            signatures="\n".join(signatures),
        )

        response = self._llm.complete(prompt)
        source_code = self._extract_code(response)

        name = usage_context.name or "_".join(usage_context.calls[:3])
        return GeneratedHarness(
            function_name=f"sequence_{name}",
            file_path=f"harness_seq_{self._sanitize_name(name)}.cpp",
            source_code=source_code,
            includes=self._extract_includes(source_code),
            compile_flags=self._default_compile_flags(),
            link_flags=self._default_link_flags(),
        )

    def _generate_sequence_from_template(
        self,
        usage_context: UsageContext,
        functions: list[FunctionInfo],
    ) -> GeneratedHarness:
        """Generate harness for a call sequence using template with FuzzedDataProvider."""
        func_map = {f.name: f for f in functions}

        # Collect includes from all functions in the sequence
        includes_set: set[str] = set()
        for call in usage_context.calls:
            if call in func_map:
                func = func_map[call]
                if func.file_path:
                    header = func.file_path.replace(".c", ".h").replace(".cpp", ".h")
                    includes_set.add(f'#include "{header}"')
                for inc in func.includes:
                    includes_set.add(inc)
        includes_str = "\n".join(sorted(includes_set))

        # Build body with calls
        body = self._build_sequence_body(usage_context, func_map)

        source_code = CPP_HARNESS_TEMPLATE.format(
            includes=includes_str,
            body=body,
        )

        name = usage_context.name or "_".join(usage_context.calls[:3])
        return GeneratedHarness(
            function_name=f"sequence_{name}",
            file_path=f"harness_seq_{self._sanitize_name(name)}.cpp",
            source_code=source_code,
            includes=self._extract_includes(source_code),
            compile_flags=self._default_compile_flags(),
            link_flags=self._default_link_flags(),
        )

    def _build_sequence_body(
        self,
        usage_context: UsageContext,
        func_map: dict[str, FunctionInfo],
    ) -> str:
        """Build harness body for a sequence of function calls."""
        lines: list[str] = []

        # Comment with sequence info
        lines.append(f"    // Fuzz harness for call sequence: {' -> '.join(usage_context.calls)}")
        if usage_context.description:
            lines.append(f"    // {usage_context.description}")
        lines.append("")

        # Early exit
        lines.append("    if (size < 1) return 0;")
        lines.append("")

        # Track resources that need cleanup
        resources: list[tuple[str, str]] = []  # (var_name, cleanup_call)

        for i, call in enumerate(usage_context.calls):
            lines.append(f"    // Step {i + 1}: {call}")

            if call in func_map:
                func = func_map[call]
                parsed_params = [parse_parameter(p) for p in func.parameters]
                pairs = find_buffer_size_pairs(parsed_params)

                # Generate consume code for each parameter
                arg_names: list[str] = []
                for param, size_param in pairs:
                    code, var_name, size_var_name = generate_fdp_consume(param, size_param, f"step{i}_")
                    lines.append(code)
                    if size_var_name:
                        arg_names.append(var_name)
                        arg_names.append(size_var_name)
                    else:
                        arg_names.append(var_name)

                # Generate call
                args_str = ", ".join(arg_names)
                if func.return_type and func.return_type.strip() not in ("void", ""):
                    lines.append(f"    auto result_{i} = {call}({args_str});")
                    # Check for common resource patterns
                    if self._is_resource_type(func.return_type):
                        resources.append((f"result_{i}", call))
                else:
                    lines.append(f"    {call}({args_str});")
            else:
                # Unknown function
                lines.append(f"    // TODO: {call}(...);")

            lines.append("")

        # Add cleanup hints
        if resources:
            lines.append("    // Cleanup (TODO: add proper cleanup calls)")
            for var_name, create_call in resources:
                lines.append(f"    // TODO: cleanup {var_name} from {create_call}")

        return "\n".join(lines)

    def _is_resource_type(self, return_type: str) -> bool:
        """Check if return type is likely a resource that needs cleanup."""
        resource_patterns = [
            r"\*$",  # pointer
            r"_t\s*\*$",  # typedef pointer
            r"handle",
            r"ptr",
            r"FILE",
        ]
        return_lower = return_type.lower()
        for pattern in resource_patterns:
            if re.search(pattern, return_lower):
                return True
        return False

    def _build_template_body(self, func: FunctionInfo) -> str:
        """Build harness body from function signature (legacy, simple version)."""
        lines = []
        lines.append(f"    // Fuzz harness for {func.name}")
        lines.append(f"    // Signature: {func.signature}")
        lines.append("")

        # Check minimum size
        lines.append("    if (size < 1) return 0;")
        lines.append("")

        # Build call with placeholder arguments
        if func.parameters:
            lines.append("    // TODO: parse fuzz input and call function")
            lines.append(f"    // {func.name}(...);")
        else:
            lines.append(f"    {func.name}();")

        return "\n".join(lines)

    def _build_fdp_body(self, func: FunctionInfo, parsed_params: list[ParsedParam]) -> str:
        """Build harness body using FuzzedDataProvider for parameter generation."""
        lines: list[str] = []

        # Comment with function info
        lines.append(f"    // Fuzz harness for: {func.name}")
        lines.append(f"    // Signature: {func.signature}")
        lines.append("")

        # Early exit if not enough data
        lines.append("    if (size < 1) return 0;")
        lines.append("")

        if not parsed_params:
            # No parameters - simple call
            lines.append(f"    {func.name}();")
            return "\n".join(lines)

        # Find buffer-size pairs
        pairs = find_buffer_size_pairs(parsed_params)

        # Reserved names that can't be used as variable names
        reserved = {"data", "size", "fdp", "result"}

        # Parameter semantics from analyze stage (one per parameter, by index)
        semantics: list[str] = getattr(func, "parameter_semantics", None) or []

        # Generate consume code for each parameter; track FILE_HANDLE vars for cleanup
        arg_names: list[str] = []
        consumed_size_params: set[str] = set()
        cleanup_handles: list[str] = []  # FILE* vars to fclose after call
        param_index = 0

        for param, size_param in pairs:
            if size_param:
                consumed_size_params.add(size_param.name)

            # Semantic override from analyze stage (FILE_PATH, FILE_HANDLE, CALLBACK, USERDATA, etc.)
            semantic_override: str | None = None
            if param_index < len(semantics):
                role = semantics[param_index]
                if role in ("FILE_PATH", "FILE_HANDLE", "CALLBACK", "USERDATA", "CONFIG_PATH", "URL"):
                    semantic_override = role

            # Determine if we need a prefix for reserved names
            name_prefix = ""
            if (param.name and param.name in reserved) or (size_param and size_param.name in reserved):
                name_prefix = "fuzz_"

            code, var_name, size_var_name = generate_fdp_consume(
                param, size_param, name_prefix, semantic_override=semantic_override
            )
            lines.append(code)
            param_index += 2 if size_param else 1

            if semantic_override == "FILE_HANDLE":
                cleanup_handles.append(var_name)

            # Add both buffer and size to args when they're paired
            if size_param and size_var_name:
                arg_names.append(var_name)
                arg_names.append(size_var_name)
            else:
                arg_names.append(var_name)

        lines.append("")

        # Generate function call
        args_str = ", ".join(arg_names)
        if func.return_type and func.return_type.strip() not in ("void", ""):
            lines.append(f"    auto result = {func.name}({args_str});")
            lines.append("    (void)result;  // Prevent unused variable warning")
        else:
            lines.append(f"    {func.name}({args_str});")

        # Cleanup FILE_HANDLE (fclose) after call
        for handle_var in cleanup_handles:
            lines.append(f"    if ({handle_var}) fclose({handle_var});")

        return "\n".join(lines)

    def _extract_code(self, response: str) -> str:
        """Extract code from LLM response (handles markdown code blocks)."""
        # Try to extract from markdown code block
        code_block = re.search(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", response, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()

        # If no code block, assume the whole response is code
        # But strip any leading/trailing non-code text
        lines = response.strip().split("\n")
        code_lines = []
        in_code = False

        for line in lines:
            if line.strip().startswith("#include") or line.strip().startswith("extern"):
                in_code = True
            if in_code:
                code_lines.append(line)

        return "\n".join(code_lines) if code_lines else response.strip()

    def _extract_includes(self, source_code: str) -> list[str]:
        """Extract #include directives from source code."""
        includes = []
        for line in source_code.split("\n"):
            line = line.strip()
            if line.startswith("#include"):
                includes.append(line)
        return includes

    def _sanitize_name(self, name: str) -> str:
        """Sanitize function name for use in filename."""
        # Replace non-alphanumeric with underscore
        sanitized = re.sub(r"[^a-zA-Z0-9]", "_", name)
        # Collapse multiple underscores
        sanitized = re.sub(r"_+", "_", sanitized)
        # Remove leading/trailing underscores
        return sanitized.strip("_")[:50]  # Limit length

    def _default_compile_flags(self) -> list[str]:
        """Return default compile flags for fuzzing."""
        return [
            "-g",
            "-O1",
            "-fno-omit-frame-pointer",
            "-fsanitize=fuzzer,address",
            "-fsanitize-address-use-after-scope",
        ]

    def _default_link_flags(self) -> list[str]:
        """Return default link flags for fuzzing."""
        return ["-fsanitize=fuzzer,address"]

    def write_harnesses(
        self,
        harnesses: list[GeneratedHarness],
        output_dir: Path | None = None,
        use_subdirs: bool = True,
    ) -> list[Path]:
        """Write harnesses to files and return paths. If use_subdirs and harness.category is set, write to output_dir/category/file_path."""
        out = Path(output_dir or self._output_dir)
        if not out:
            raise ValueError("output_dir not specified")

        out.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        for harness in harnesses:
            if not harness.source_code:
                continue
            if use_subdirs and getattr(harness, "category", ""):
                subdir = out / harness.category
                subdir.mkdir(parents=True, exist_ok=True)
                file_path = subdir / harness.file_path
            else:
                file_path = out / harness.file_path
            file_path.write_text(harness.source_code)
            written.append(file_path)
            log.debug("Wrote harness: %s", file_path)

        return written
