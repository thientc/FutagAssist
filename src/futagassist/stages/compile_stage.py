"""Compile stage: compile fuzz harnesses into instrumented binaries."""

from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

from futagassist.core.schema import GeneratedHarness, PipelineContext, StageResult
from futagassist.utils import get_llm_provider, get_registry_and_config, resolve_output_dir

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Named constants (avoid magic numbers)
# ---------------------------------------------------------------------------

#: Maximum number of compiler error lines kept when building the LLM prompt.
MAX_COMPILER_ERROR_LINES = 10

#: Upper bound (seconds) for the exponential-backoff delay between retries.
MAX_BACKOFF_SECONDS = 30

#: Default per-harness compilation timeout (seconds).
DEFAULT_COMPILE_TIMEOUT = 120

#: Maximum characters of compiler error output sent to the LLM.
MAX_ERROR_OUTPUT_CHARS = 4000

#: Maximum characters of harness source code sent to the LLM.
MAX_SOURCE_CODE_CHARS = 8000

# Default flags when no LanguageAnalyzer is available or for C/C++ harnesses.
DEFAULT_COMPILE_FLAGS = [
    "-fsanitize=fuzzer,address",
    "-fprofile-instr-generate",
    "-fcoverage-mapping",
    "-g",
    "-O1",
    "-fno-omit-frame-pointer",
]

# LLM prompt for fixing compilation errors.
COMPILE_FIX_PROMPT = """A fuzz harness failed to compile. Suggest an edited version of the
source that fixes the error.  Return ONLY the corrected C/C++ source
(no markdown fences, no explanation).  If unfixable, reply with exactly: UNFIXABLE

Compiler command: {compile_cmd}

Source file: {source_file}

Error output:
---
{error_output}
---

Original source:
```
{source_code}
```

Corrected source:"""


def _parse_compiler_errors(stderr: str) -> list[str]:
    """Extract short error lines from compiler output."""
    errors: list[str] = []
    for line in stderr.splitlines():
        if "error:" in line.lower() or "fatal error:" in line.lower():
            errors.append(line.strip())
    return errors[:MAX_COMPILER_ERROR_LINES]  # cap to keep prompt short


class CompileStage:
    """Pipeline stage that compiles generated fuzz harnesses into instrumented binaries.

    Features:
    - Compiler flags from ``LanguageAnalyzer.get_compiler_flags()``
    - Linking against ``fuzz_install_prefix`` from the fuzz-build stage
    - LLM-assisted compilation error fixing with retry and exponential backoff
    - Coverage instrumentation (``-fprofile-instr-generate -fcoverage-mapping``)
    """

    name = "compile"
    depends_on: list[str] = ["generate", "fuzz_build"]

    def execute(self, context: PipelineContext) -> StageResult:
        """Compile each harness source into a binary."""
        harnesses = context.generated_harnesses
        if not harnesses:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="No generated harnesses in context (run generate stage first).",
            )

        # Filter to valid harnesses only
        valid_harnesses = [h for h in harnesses if h.is_valid and h.source_code]
        if not valid_harnesses:
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"No valid harnesses to compile ({len(harnesses)} total, 0 valid with source).",
            )

        registry, config_manager, err = get_registry_and_config(context, self.name)
        if err:
            return err

        cfg = config_manager.config
        avail = registry.list_available()

        # Resolve output directory for binaries
        binaries_dir = resolve_output_dir(context, "compile_output", "fuzz_binaries")

        # Get compiler flags from language analyzer
        language = context.language or cfg.language
        compiler_flags = list(DEFAULT_COMPILE_FLAGS)
        try:
            if language in avail.get("language_analyzers", []):
                analyzer = registry.get_language(language)
                plugin_flags = analyzer.get_compiler_flags()
                if plugin_flags:
                    compiler_flags = plugin_flags
                    log.info("Using compiler flags from %s analyzer: %s", language, compiler_flags)
        except Exception as e:
            log.warning("Failed to get compiler flags from language analyzer: %s", e)

        # Get LLM for error fixing
        llm = None
        use_llm = context.config.get("compile_use_llm", True)
        if use_llm:
            llm = get_llm_provider(registry, config_manager, avail=avail)
            if llm:
                log.info("LLM available for compile-error fixing: %s", cfg.llm_provider)
            else:
                log.warning("Failed to initialize LLM for compile fixes")

        max_retries = context.config.get("compile_max_retries", cfg.llm.max_retries)
        compiler = context.config.get("compile_compiler", "clang++")
        timeout = context.config.get("compile_timeout", DEFAULT_COMPILE_TIMEOUT)

        # Build link flags from fuzz_install_prefix
        link_flags: list[str] = []
        fuzz_prefix = context.fuzz_install_prefix
        if fuzz_prefix and Path(fuzz_prefix).is_dir():
            p = Path(fuzz_prefix)
            if (p / "lib").is_dir():
                link_flags.extend([f"-L{p / 'lib'}", f"-Wl,-rpath,{p / 'lib'}"])
            if (p / "include").is_dir():
                link_flags.append(f"-I{p / 'include'}")
            log.info("Linking against fuzz install prefix: %s", fuzz_prefix)

        compiled: list[dict] = []
        failed: list[dict] = []

        for harness in valid_harnesses:
            binary_name = _binary_name(harness)
            binary_path = binaries_dir / binary_name

            # Write source to temp file
            source_path = binaries_dir / f"{binary_name}.cpp"
            source_path.write_text(harness.source_code, encoding="utf-8")

            success, final_binary, error_msg = self._compile_harness(
                source_path=source_path,
                binary_path=binary_path,
                compiler=compiler,
                compiler_flags=compiler_flags,
                harness_compile_flags=harness.compile_flags,
                link_flags=link_flags + harness.link_flags,
                llm=llm,
                max_retries=max_retries,
                timeout=timeout,
                harness=harness,
            )
            if success:
                compiled.append({
                    "function_name": harness.function_name,
                    "binary_path": str(final_binary),
                    "source_path": str(source_path),
                })
            else:
                failed.append({
                    "function_name": harness.function_name,
                    "source_path": str(source_path),
                    "error": error_msg,
                })

        total = len(valid_harnesses)
        ok_count = len(compiled)
        fail_count = len(failed)
        log.info(
            "Compilation done: %d/%d succeeded, %d failed",
            ok_count, total, fail_count,
        )

        data: dict = {
            "binaries_dir": str(binaries_dir),
            "compiled": compiled,
            "failed": failed,
            "compiled_count": ok_count,
            "failed_count": fail_count,
        }

        if ok_count == 0:
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"All {total} harnesses failed to compile.",
                data=data,
            )

        return StageResult(
            stage_name=self.name,
            success=True,
            message=f"Compiled {ok_count}/{total} harnesses ({fail_count} failed).",
            data=data,
        )

    def _compile_harness(
        self,
        source_path: Path,
        binary_path: Path,
        compiler: str,
        compiler_flags: list[str],
        harness_compile_flags: list[str],
        link_flags: list[str],
        llm: object | None,
        max_retries: int,
        timeout: int,
        harness: GeneratedHarness,
    ) -> tuple[bool, Path | None, str]:
        """Compile a single harness. Returns (success, binary_path, error_msg).

        On failure, if an LLM is available, asks it to fix the source and retries
        with exponential backoff (1s, 2s, 4s, ...).
        """
        cmd = self._build_compile_cmd(
            compiler, source_path, binary_path,
            compiler_flags, harness_compile_flags, link_flags,
        )
        log.info("Compiling %s: %s", harness.function_name, " ".join(cmd))

        # First attempt
        ok, stderr = self._run_compiler(cmd, source_path.parent, timeout)
        if ok:
            return True, binary_path, ""

        last_error = stderr
        log.warning("Compilation failed for %s: %s", harness.function_name, _parse_compiler_errors(stderr))

        # LLM-assisted retry loop with exponential backoff
        if llm is None or max_retries < 1:
            return False, None, last_error

        current_source = harness.source_code
        for attempt in range(max_retries):
            backoff = min(2 ** attempt, MAX_BACKOFF_SECONDS)
            log.info(
                "Retry %d/%d for %s (backoff %ds)",
                attempt + 1, max_retries, harness.function_name, backoff,
            )
            time.sleep(backoff)

            fixed_source = self._ask_llm_for_fix(
                llm, " ".join(cmd), str(source_path), last_error, current_source
            )
            if fixed_source is None:
                log.warning("LLM could not fix %s; stopping retries", harness.function_name)
                break

            # Write fixed source and retry compilation
            source_path.write_text(fixed_source, encoding="utf-8")
            current_source = fixed_source

            ok, stderr = self._run_compiler(cmd, source_path.parent, timeout)
            if ok:
                log.info("LLM fix succeeded for %s on retry %d", harness.function_name, attempt + 1)
                return True, binary_path, ""

            last_error = stderr
            log.warning(
                "Retry %d failed for %s: %s",
                attempt + 1, harness.function_name, _parse_compiler_errors(stderr)[:3],
            )

        return False, None, last_error

    @staticmethod
    def _build_compile_cmd(
        compiler: str,
        source_path: Path,
        binary_path: Path,
        compiler_flags: list[str],
        harness_compile_flags: list[str],
        link_flags: list[str],
    ) -> list[str]:
        """Build the compiler command as a list of arguments."""
        cmd = [compiler]
        cmd.extend(compiler_flags)
        cmd.extend(harness_compile_flags)
        cmd.append(str(source_path))
        cmd.extend(["-o", str(binary_path)])
        cmd.extend(link_flags)
        return cmd

    @staticmethod
    def _run_compiler(cmd: list[str], cwd: Path, timeout: int) -> tuple[bool, str]:
        """Run compiler and return (success, stderr)."""
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
        except subprocess.TimeoutExpired:
            return False, f"Compilation timed out ({timeout}s)"
        except FileNotFoundError:
            return False, f"Compiler not found: {cmd[0]}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _ask_llm_for_fix(
        llm: object,
        compile_cmd: str,
        source_file: str,
        error_output: str,
        source_code: str,
    ) -> str | None:
        """Ask LLM to fix compilation errors. Returns fixed source or None."""
        prompt = COMPILE_FIX_PROMPT.format(
            compile_cmd=compile_cmd,
            source_file=source_file,
            error_output=error_output[:MAX_ERROR_OUTPUT_CHARS],
            source_code=source_code[:MAX_SOURCE_CODE_CHARS],
        )
        try:
            response = llm.complete(prompt).strip()  # type: ignore[union-attr]
            if not response or response.upper() == "UNFIXABLE":
                return None
            # Strip markdown fences if present
            if response.startswith("```"):
                response = re.sub(r"^```\w*\n?", "", response)
            if response.endswith("```"):
                response = response.rsplit("```", 1)[0]
            response = response.strip()
            # Sanity: must contain LLVMFuzzerTestOneInput or main
            if "LLVMFuzzerTestOneInput" not in response and "int main" not in response:
                return None
            return response
        except Exception as e:
            log.warning("LLM compile-fix request failed: %s", e)
            return None

    def can_skip(self, context: PipelineContext) -> bool:
        """Can skip if binaries_dir already set and contains binaries."""
        if context.binaries_dir and Path(context.binaries_dir).is_dir():
            binaries = list(Path(context.binaries_dir).glob("*"))
            # Check for at least one executable file
            return any(f.is_file() and not f.suffix for f in binaries)
        return False


def _binary_name(harness: GeneratedHarness) -> str:
    """Derive a binary name from the harness function name."""
    # Sanitize function name for filesystem
    name = re.sub(r"[^a-zA-Z0-9_]", "_", harness.function_name)
    return f"fuzz_{name}"
