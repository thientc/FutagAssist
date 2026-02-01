"""Syntax validator: validates generated harness code for syntax errors."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from futagassist.core.schema import GeneratedHarness

log = logging.getLogger(__name__)


class SyntaxValidator:
    """Validates C/C++ syntax of generated harnesses using compiler."""

    def __init__(
        self,
        compiler: str = "clang++",
        language: str = "cpp",
        extra_flags: list[str] | None = None,
    ) -> None:
        self._compiler = compiler
        self._language = language
        self._extra_flags = extra_flags or []

    def validate(self, harness: GeneratedHarness) -> GeneratedHarness:
        """Validate harness syntax and update validation status."""
        if not harness.source_code:
            harness.is_valid = False
            harness.validation_errors.append("No source code")
            return harness

        errors = self._check_syntax(harness.source_code)
        if errors:
            harness.is_valid = False
            harness.validation_errors.extend(errors)
        else:
            harness.is_valid = True
            harness.validation_errors = []

        return harness

    def validate_batch(self, harnesses: list[GeneratedHarness]) -> list[GeneratedHarness]:
        """Validate multiple harnesses."""
        return [self.validate(h) for h in harnesses]

    def _check_syntax(self, source_code: str) -> list[str]:
        """Check C/C++ syntax using compiler. Returns list of errors."""
        compiler_path = shutil.which(self._compiler)
        if not compiler_path:
            log.warning("Compiler %s not found, skipping syntax check", self._compiler)
            return []

        errors: list[str] = []

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".cpp" if self._language == "cpp" else ".c",
            delete=False,
        ) as f:
            f.write(source_code)
            temp_path = Path(f.name)

        try:
            # Syntax check only (-fsyntax-only), don't link
            cmd = [
                self._compiler,
                "-fsyntax-only",
                "-std=c++17" if self._language == "cpp" else "-std=c11",
                "-Wall",
                *self._extra_flags,
                str(temp_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
                check=False,
            )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                errors = self._parse_compiler_errors(stderr)

        except subprocess.TimeoutExpired:
            errors.append("Syntax check timed out")
        except OSError as e:
            log.warning("Syntax check failed: %s", e)
        finally:
            temp_path.unlink(missing_ok=True)

        return errors

    def _parse_compiler_errors(self, stderr: str) -> list[str]:
        """Parse compiler stderr to extract error messages."""
        errors: list[str] = []
        for line in stderr.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Look for error lines (clang/gcc format)
            if ": error:" in line or ": fatal error:" in line:
                # Extract just the error part, not the full path
                match = re.search(r":\d+:\d+: (error|fatal error): (.+)", line)
                if match:
                    errors.append(match.group(2))
                else:
                    errors.append(line)
            elif line.startswith("error:"):
                errors.append(line[6:].strip())

        return errors[:5]  # Limit to first 5 errors

    def check_basic_structure(self, harness: GeneratedHarness) -> list[str]:
        """Quick structural checks without compiler."""
        errors: list[str] = []
        code = harness.source_code

        # Check for LLVMFuzzerTestOneInput
        if "LLVMFuzzerTestOneInput" not in code:
            errors.append("Missing LLVMFuzzerTestOneInput entry point")

        # Check for basic includes
        if "#include" not in code:
            errors.append("Missing #include directives")

        # Check for return statement
        if "return" not in code:
            errors.append("Missing return statement")

        # Check balanced braces
        if code.count("{") != code.count("}"):
            errors.append("Unbalanced braces")

        # Check balanced parentheses
        if code.count("(") != code.count(")"):
            errors.append("Unbalanced parentheses")

        return errors

    def quick_validate(self, harness: GeneratedHarness) -> GeneratedHarness:
        """Quick validation without compiler (structural checks only)."""
        errors = self.check_basic_structure(harness)
        if errors:
            harness.is_valid = False
            harness.validation_errors.extend(errors)
        else:
            harness.is_valid = True
        return harness
