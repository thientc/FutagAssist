"""Health checks for CodeQL, LLM, plugins, and other components."""

from __future__ import annotations

import os
import shutil
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
    suggestion: str = ""


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


def _resolve_codeql_bin(config: ConfigManager) -> tuple[str, Path | None]:
    """Resolve codeql binary path (same logic as C++ plugin). Returns (binary_str, absolute_path or None)."""
    codeql_home = config.config.codeql_home
    if codeql_home:
        home = Path(codeql_home).resolve()
        for subpath in ("codeql", "bin/codeql"):
            candidate = home / subpath
            if candidate.exists():
                return str(candidate), candidate
        return str(home / "bin" / "codeql"), None
    # From PATH
    found = shutil.which("codeql")
    if found:
        return found, Path(found).resolve()
    return "codeql", None


def _codeql_resolve_packs(codeql_bin: str, search_path: list[Path] | None, timeout: int = 8) -> tuple[bool, str]:
    """Run codeql resolve packs; return (success, output). Used to verify QL packs (e.g. cpp) are found."""
    try:
        args = [codeql_bin, "resolve", "packs"]
        if search_path:
            path_str = ":".join(str(p) for p in search_path if p.exists())
            if path_str:
                args.append(f"--search-path={path_str}")
        ok, out = _run_cmd(args, timeout=timeout)
        return ok, out or ""
    except Exception:
        return False, ""


class HealthChecker:
    """Run health checks for CodeQL, LLM provider, plugins, and fuzzer requirements."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        registry: ComponentRegistry | None = None,
    ) -> None:
        self._config = config or ConfigManager()
        self._registry = registry or ComponentRegistry()

    def check_codeql(self, *, verify_packs: bool = True) -> HealthCheckResult:
        """Check that CodeQL CLI is available, returns a version, and (optionally) can resolve QL packs (e.g. cpp)."""
        codeql_bin_str, codeql_bin_path = _resolve_codeql_bin(self._config)
        # Version check
        ok, out = _run_cmd([codeql_bin_str, "version", "--quiet"])
        if not ok:
            suggestion = (
                "Install the CodeQL bundle from https://github.com/github/codeql-action/releases, "
                "then set CODEQL_HOME to the directory containing the 'codeql' executable "
                "(e.g. <extraction-root>/codeql), or add that directory to PATH."
            )
            return HealthCheckResult(
                name="codeql",
                ok=False,
                message=out or "codeql version failed. Install CodeQL CLI or set CODEQL_HOME.",
                suggestion=suggestion,
            )
        message = out or "OK"
        if codeql_bin_path:
            message = f"{message} (binary: {codeql_bin_path})"

        # Optionally verify that QL packs (e.g. cpp) can be resolved (needed for futagassist analyze).
        # Run resolve packs without --search-path so the CLI uses its default "root of CodeQL distribution"
        # (inferred from the binary path). That way the bundle is detected correctly when codeql is from the bundle.
        suggestion = ""
        if verify_packs:
            packs_ok, packs_out = _codeql_resolve_packs(codeql_bin_str, search_path=None)
            if not packs_ok or ("codeql/cpp" not in packs_out and "codeql/cpp-all" not in packs_out):
                suggestion = (
                    "For 'futagassist analyze' you need the CodeQL bundle (includes cpp pack). "
                    "Set CODEQL_HOME to the bundle's codeql directory (e.g. <extraction-root>/codeql) or add it to PATH."
                )

        return HealthCheckResult(
            name="codeql",
            ok=True,
            message=message,
            suggestion=suggestion,
        )

    def check_llm(self) -> HealthCheckResult:
        """Check selected LLM provider if registered and healthy."""
        provider_name = self._config.config.llm_provider
        avail = self._registry.list_available()["llm_providers"]
        if provider_name not in avail:
            suggestion = (
                "Run from the FutagAssist project root (where plugins/ exists) so LLM plugins load, "
                "or add your plugin to plugins/llm/ and implement register(registry)."
            )
            return HealthCheckResult(
                name="llm",
                ok=False,
                message=f"No LLM provider '{provider_name}' registered. Available: {', '.join(avail) or 'none'}.",
                suggestion=suggestion,
            )
        try:
            provider = self._registry.get_llm(
                provider_name,
                **self._config.env,
            )
            if provider.check_health():
                return HealthCheckResult(name="llm", ok=True, message=f"{provider_name} OK")
            suggestion = "Set OPENAI_API_KEY in .env or environment for the OpenAI provider."
            if provider_name != "openai":
                suggestion = f"Check {provider_name} configuration (API key, base URL) in .env or config."
            return HealthCheckResult(
                name="llm",
                ok=False,
                message=f"{provider_name} check_health() failed",
                suggestion=suggestion,
            )
        except Exception as e:
            suggestion = "Set OPENAI_API_KEY in .env (or the provider's required env vars) and ensure the key is valid."
            return HealthCheckResult(
                name="llm",
                ok=False,
                message=str(e),
                suggestion=suggestion,
            )

    def check_fuzzer(self) -> HealthCheckResult:
        """Check that selected fuzzer engine's requirements are met (e.g. clang for libFuzzer)."""
        engine_name = self._config.config.fuzzer_engine
        if engine_name not in self._registry.list_available()["fuzzer_engines"]:
            return HealthCheckResult(
                name="fuzzer",
                ok=False,
                message=f"No fuzzer engine '{engine_name}' registered.",
                suggestion="Fuzzer engines are loaded from plugins/; run from project root or add a fuzzer plugin.",
            )
        if engine_name == "libfuzzer":
            ok_c, out_c = _run_cmd(["clang", "--version"])
            ok_cxx, out_cxx = _run_cmd(["clang++", "--version"])
            if ok_c and ok_cxx:
                return HealthCheckResult(name="fuzzer", ok=True, message="clang and clang++ found")
            missing = []
            if not ok_c:
                missing.append("clang")
            if not ok_cxx:
                missing.append("clang++")
            return HealthCheckResult(
                name="fuzzer",
                ok=False,
                message=f"{', '.join(missing)} not found. libFuzzer requires clang/clang++.",
                suggestion="Install LLVM/clang (e.g. apt install clang, or download from llvm.org).",
            )
        return HealthCheckResult(name="fuzzer", ok=True, message=f"{engine_name} registered")

    def check_plugins(self) -> HealthCheckResult:
        """Check that plugins are loaded and the configured language has an analyzer (e.g. cpp)."""
        root = self._config.project_root
        plugins_dir = root / "plugins"
        avail = self._registry.list_available()
        lang = self._config.config.language
        analyzers = avail.get("language_analyzers", [])

        if not plugins_dir.is_dir():
            suggestion = (
                f"Run from the FutagAssist project root (directory containing plugins/). "
                f"Or create a plugins/ directory with language analyzers (e.g. plugins/cpp/ for cpp)."
            )
            return HealthCheckResult(
                name="plugins",
                ok=False,
                message=f"No plugins directory at {plugins_dir}. Language analyzers: none.",
                suggestion=suggestion,
            )

        if lang not in analyzers:
            suggestion = (
                f"For language '{lang}', add a plugin that registers a LanguageAnalyzer. "
                f"FutagAssist includes plugins/cpp/ for cpp; run from the project root so it loads."
            )
            return HealthCheckResult(
                name="plugins",
                ok=False,
                message=f"No language analyzer for '{lang}'. Available: {', '.join(analyzers) or 'none'}.",
                suggestion=suggestion,
            )

        summary = ", ".join(f"{k}: {len(v)}" for k, v in avail.items() if v)
        return HealthCheckResult(
            name="plugins",
            ok=True,
            message=f"plugins/ loaded ({summary}). Language '{lang}' has analyzer.",
        )

    def check_all(
        self,
        *,
        skip_llm: bool = False,
        skip_fuzzer: bool = False,
        skip_plugins: bool = False,
        verify_codeql_packs: bool = False,
    ) -> list[HealthCheckResult]:
        """Run all enabled checks. Set verify_codeql_packs=True to ensure cpp pack is found (slower)."""
        results: list[HealthCheckResult] = []
        results.append(self.check_codeql(verify_packs=verify_codeql_packs))
        if not skip_plugins:
            results.append(self.check_plugins())
        if not skip_llm:
            results.append(self.check_llm())
        if not skip_fuzzer:
            results.append(self.check_fuzzer())
        return results
