"""Health checks for CodeQL, LLM, and other components."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from futagassist.core.config import ConfigManager
from futagassist.core.registry import ComponentRegistry


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    name: str
    ok: bool
    message: str = ""


def _run_cmd(cmd: list[str], timeout: int = 5) -> tuple[bool, str]:
    """Run command, return (success, output_or_error)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, (result.stdout or "").strip()
        return False, result.stderr or result.stdout or f"exit code {result.returncode}"
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


class HealthChecker:
    """Run health checks for CodeQL, LLM provider, and fuzzer requirements."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        registry: ComponentRegistry | None = None,
    ) -> None:
        self._config = config or ConfigManager()
        self._registry = registry or ComponentRegistry()

    def check_codeql(self) -> HealthCheckResult:
        """Check that CodeQL CLI is available and returns a version."""
        codeql_home = self._config.config.codeql_home
        if codeql_home:
            codeql_bin = Path(codeql_home).resolve() / "bin" / "codeql"
            if not codeql_bin.exists():
                return HealthCheckResult(
                    name="codeql",
                    ok=False,
                    message=f"CODEQL_HOME/bin/codeql not found: {codeql_bin}",
                )
            ok, out = _run_cmd([str(codeql_bin), "version", "--quiet"])
        else:
            ok, out = _run_cmd(["codeql", "version", "--quiet"])
        if ok:
            return HealthCheckResult(name="codeql", ok=True, message=out or "OK")
        return HealthCheckResult(
            name="codeql",
            ok=False,
            message=out or "Run 'codeql version' failed. Install CodeQL CLI or set CODEQL_HOME.",
        )

    def check_llm(self) -> HealthCheckResult:
        """Check selected LLM provider if registered."""
        provider_name = self._config.config.llm_provider
        if provider_name not in self._registry.list_available()["llm_providers"]:
            return HealthCheckResult(
                name="llm",
                ok=False,
                message=f"No LLM provider '{provider_name}' registered. Run from a directory with plugins/ or register a provider.",
            )
        try:
            provider = self._registry.get_llm(
                provider_name,
                **self._config.env,
            )
            if provider.check_health():
                return HealthCheckResult(name="llm", ok=True, message=f"{provider_name} OK")
            return HealthCheckResult(name="llm", ok=False, message=f"{provider_name} check_health() failed")
        except Exception as e:
            return HealthCheckResult(name="llm", ok=False, message=str(e))

    def check_fuzzer(self) -> HealthCheckResult:
        """Check that selected fuzzer engine's requirements are met (e.g. clang for libFuzzer)."""
        engine_name = self._config.config.fuzzer_engine
        if engine_name not in self._registry.list_available()["fuzzer_engines"]:
            return HealthCheckResult(
                name="fuzzer",
                ok=False,
                message=f"No fuzzer engine '{engine_name}' registered.",
            )
        if engine_name == "libfuzzer":
            ok, out = _run_cmd(["clang", "--version"])
            if ok:
                return HealthCheckResult(name="fuzzer", ok=True, message="clang found")
            return HealthCheckResult(
                name="fuzzer",
                ok=False,
                message="clang not found. libFuzzer requires clang. Install LLVM/clang.",
            )
        return HealthCheckResult(name="fuzzer", ok=True, message=f"{engine_name} registered")

    def check_all(self, *, skip_llm: bool = False, skip_fuzzer: bool = False) -> list[HealthCheckResult]:
        """Run all enabled checks."""
        results: list[HealthCheckResult] = []
        results.append(self.check_codeql())
        if not skip_llm:
            results.append(self.check_llm())
        if not skip_fuzzer:
            results.append(self.check_fuzzer())
        return results
