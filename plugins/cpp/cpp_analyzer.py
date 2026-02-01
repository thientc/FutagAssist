"""C/C++ language analyzer for FutagAssist.

Registers as language 'cpp'. Uses CodeQL to extract functions from a CodeQL database.
CodeQL query template: list_functions.ql in this directory (plugins/cpp/list_functions.ql).
"""

from __future__ import annotations

import csv
import logging
import os
import subprocess
import shutil
from pathlib import Path

from futagassist.analysis.codeql_runner import CodeQLRunner
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import FunctionInfo, UsageContext

log = logging.getLogger(__name__)


def _codeql_bin() -> str:
    """Resolve codeql binary (respect CODEQL_HOME like build stage)."""
    if os.environ.get("CODEQL_HOME"):
        home = Path(os.environ["CODEQL_HOME"]).resolve()
        # Bundle: CODEQL_HOME/codeql; some installs: CODEQL_HOME/bin/codeql
        for subpath in ("codeql", "bin/codeql"):
            candidate = home / subpath
            if candidate.exists():
                return str(candidate)
        return str(home / "bin" / "codeql")
    return "codeql"


def _codeql_binary_path() -> Path | None:
    """Return absolute path to the codeql binary, or None if not found."""
    bin_str = _codeql_bin()
    if os.path.isabs(bin_str) or "/" in bin_str:
        p = Path(bin_str).resolve()
        return p if p.exists() else None
    found = shutil.which(bin_str)
    return Path(found).resolve() if found else None


def _is_bundle_install() -> bool:
    """True if CodeQL appears to be a bundle install (binary and qlpacks in same tree).
    
    In a bundle, we should NOT pass --search-path because CodeQL auto-discovers
    its packs from the distribution root.
    """
    binary_path = _codeql_binary_path()
    if not binary_path:
        return False
    # Check if qlpacks/ is a sibling or in parent (bundle layouts)
    for base in (binary_path.parent, binary_path.parent.parent):
        qlpacks = base / "qlpacks"
        if qlpacks.is_dir() and (qlpacks / "codeql" / "cpp-all").is_dir():
            return True
    return False


def _codeql_search_path() -> list[Path]:
    """Directories for CodeQL to find QL packs (e.g. codeql/cpp-all).

    When running from a CodeQL bundle, returns empty list (CodeQL auto-discovers packs).
    Only returns paths for non-bundle installs or when CODEQL_REPO is set.
    """
    # Bundle installs should use CodeQL's auto-discovery, not --search-path
    if _is_bundle_install() and not os.environ.get("CODEQL_REPO"):
        return []

    seen: set[Path] = set()
    out: list[Path] = []

    def add(p: Path) -> None:
        if p.exists() and p not in seen:
            seen.add(p)
            out.append(p)

    # CODEQL_REPO (user-set, for custom queries repo)
    if os.environ.get("CODEQL_REPO"):
        add(Path(os.environ["CODEQL_REPO"]).resolve())

    return out


class CppAnalyzer:
    """Language analyzer for C/C++ that uses CodeQL to list functions."""

    language = "cpp"

    def __init__(self) -> None:
        self._query_dir = Path(__file__).resolve().parent
        self._list_functions_ql = self._query_dir / "list_functions.ql"
        self._runner = CodeQLRunner(codeql_bin=_codeql_bin())

    def get_codeql_queries(self) -> list[Path]:
        """Return paths to CodeQL query files (list_functions.ql in plugins/cpp/)."""
        if self._list_functions_ql.exists():
            return [self._list_functions_ql]
        return []

    def extract_functions(self, db_path: Path) -> list[FunctionInfo]:
        """Run CodeQL list_functions query, decode BQRS to CSV, parse into FunctionInfo."""
        queries = self.get_codeql_queries()
        if not queries:
            log.warning("No CodeQL query found at %s", self._list_functions_ql)
            return []

        db = Path(db_path).resolve()
        search_path = _codeql_search_path()
        search_path_str = ":".join(str(p) for p in search_path) if search_path else ""
        is_bundle = _is_bundle_install()
        if search_path:
            log.debug("CodeQL --search-path: %s", search_path_str)
        elif is_bundle:
            log.debug("Running from CodeQL bundle; using auto-discovery (no --search-path).")
        else:
            log.warning(
                "No CodeQL bundle detected and CODEQL_REPO not set. "
                "Set CODEQL_HOME to the bundle root (directory containing 'codeql' binary and 'qlpacks/'). "
                "If you see 'could not resolve module cpp', install the CodeQL bundle."
            )
        result = self._runner.run_queries(
            db, queries, timeout=600, search_path=search_path if search_path else None
        )
        if result.returncode != 0:
            err_text = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")
            log.warning(
                "CodeQL run-queries failed (exit %s): %s",
                result.returncode,
                err_text[:500],
            )
            if "could not resolve module cpp" in err_text:
                binary_path = _codeql_binary_path()
                log.warning(
                    "Could not resolve 'cpp' module. Binary: %s, Bundle detected: %s. "
                    "Ensure you're using the CodeQL bundle (not standalone CLI) and that "
                    "$CODEQL_HOME/qlpacks/codeql/cpp-all/ exists.",
                    binary_path,
                    is_bundle,
                )
            return []

        # Find BQRS under db/results (e.g. results/list_functions/default/results.bqrs)
        results_dir = db / "results"
        bqrs_files = list(results_dir.rglob("*.bqrs")) if results_dir.is_dir() else []
        if not bqrs_files:
            log.warning("No BQRS files under %s", results_dir)
            return []

        functions: list[FunctionInfo] = []
        codeql_bin = _codeql_bin()
        for bqrs_path in bqrs_files:
            try:
                decode_result = subprocess.run(
                    [
                        codeql_bin,
                        "bqrs",
                        "decode",
                        "--format=csv",
                        "--no-titles",
                        "--",
                        str(bqrs_path),
                    ],
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                if decode_result.returncode != 0:
                    log.debug("bqrs decode failed for %s: %s", bqrs_path, decode_result.stderr)
                    continue
                csv_text = (decode_result.stdout or b"").decode("utf-8", errors="replace")
                reader = csv.reader(csv_text.strip().splitlines())
                # Columns from list_functions.ql:
                # file_path, line, name, qualified_name, return_type, param_count, parameters, is_public
                for row in reader:
                    if len(row) >= 4:
                        file_path = (row[0] or "").strip()
                        try:
                            line = int(row[1]) if row[1].strip() else 0
                        except ValueError:
                            line = 0
                        name = (row[2] or "").strip()
                        qualified_name = (row[3] or "").strip() or name
                        return_type = (row[4] or "").strip() if len(row) > 4 else ""
                        # param_count at row[5], not directly needed
                        params_str = (row[6] or "").strip() if len(row) > 6 else ""
                        # Parse parameters: "type1 name1, type2 name2" -> list of strings
                        parameters: list[str] = []
                        if params_str:
                            for param in params_str.split(", "):
                                param = param.strip()
                                if param:
                                    parameters.append(param)
                        # Build signature: "return_type qualified_name(params)"
                        signature = f"{return_type} {qualified_name}({params_str})"
                        functions.append(
                            FunctionInfo(
                                name=name,
                                signature=signature,
                                return_type=return_type,
                                parameters=parameters,
                                file_path=file_path,
                                line=line,
                                includes=[],
                                context="",
                            )
                        )
            except (subprocess.TimeoutExpired, OSError) as e:
                log.debug("Decode/parse error for %s: %s", bqrs_path, e)
        return functions

    def extract_usage_contexts(self, db_path: Path) -> list[UsageContext]:
        """Extract usage contexts (call sequences). Not implemented; returns empty list."""
        return []

    def generate_harness_template(self, func: FunctionInfo) -> str:
        """Return a minimal harness template for the function."""
        return f"// Fuzz harness for {func.name}\nvoid LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {{\n  // TODO: call {func.name}\n}}\n"

    def get_compiler_flags(self) -> list[str]:
        """Compiler flags for fuzz builds."""
        return ["-fsanitize=fuzzer", "-g"]


def register(registry: ComponentRegistry) -> None:
    """Register the C++ language analyzer."""
    registry.register_language("cpp", CppAnalyzer)
