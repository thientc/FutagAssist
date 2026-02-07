"""Tests for the C++ language analyzer plugin (plugins/cpp/cpp_analyzer.py)."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# The plugin lives outside the src tree; make sure it's importable.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins" / "cpp"))

from cpp_analyzer import (  # type: ignore[import-untyped]
    CppAnalyzer,
    _codeql_bin,
    _codeql_binary_path,
    _codeql_search_path,
    _is_bundle_install,
    register,
)
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import FunctionInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ===================================================================
# _codeql_bin
# ===================================================================


class TestCodeqlBin:
    """Tests for _codeql_bin() helper."""

    def test_default_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODEQL_HOME", raising=False)
        assert _codeql_bin() == "codeql"

    def test_codeql_home_with_direct_binary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When CODEQL_HOME/codeql exists, use it."""
        (tmp_path / "codeql").touch()
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        result = _codeql_bin()
        assert result.endswith("codeql")
        assert str(tmp_path) in result

    def test_codeql_home_with_bin_subdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When CODEQL_HOME/bin/codeql exists, use it."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "codeql").touch()
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        result = _codeql_bin()
        assert "bin" in result
        assert result.endswith("codeql")

    def test_codeql_home_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When CODEQL_HOME is set but no binary exists, fall back to CODEQL_HOME/bin/codeql."""
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        result = _codeql_bin()
        assert result.endswith("bin/codeql") or result.endswith("bin\\codeql")


# ===================================================================
# _codeql_binary_path
# ===================================================================


class TestCodeqlBinaryPath:
    """Tests for _codeql_binary_path() helper."""

    def test_returns_none_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODEQL_HOME", raising=False)
        with patch("cpp_analyzer.shutil.which", return_value=None):
            assert _codeql_binary_path() is None

    def test_returns_path_from_codeql_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        binary = tmp_path / "codeql"
        binary.touch()
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        result = _codeql_binary_path()
        assert result is not None
        assert result.exists()

    def test_returns_path_from_which(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("CODEQL_HOME", raising=False)
        binary = tmp_path / "codeql"
        binary.touch()
        with patch("cpp_analyzer.shutil.which", return_value=str(binary)):
            result = _codeql_binary_path()
            assert result is not None
            assert result.exists()


# ===================================================================
# _is_bundle_install
# ===================================================================


class TestIsBundleInstall:
    """Tests for _is_bundle_install() helper."""

    def test_false_when_no_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODEQL_HOME", raising=False)
        with patch("cpp_analyzer.shutil.which", return_value=None):
            assert _is_bundle_install() is False

    def test_true_when_qlpacks_sibling(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bundle layout: CODEQL_HOME/codeql binary + CODEQL_HOME/qlpacks/codeql/cpp-all/."""
        binary = tmp_path / "codeql"
        binary.touch()
        (tmp_path / "qlpacks" / "codeql" / "cpp-all").mkdir(parents=True)
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        assert _is_bundle_install() is True

    def test_true_when_qlpacks_in_parent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bundle layout: CODEQL_HOME/bin/codeql + CODEQL_HOME/qlpacks/codeql/cpp-all/."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "codeql").touch()
        (tmp_path / "qlpacks" / "codeql" / "cpp-all").mkdir(parents=True)
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        assert _is_bundle_install() is True

    def test_false_when_no_qlpacks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        binary = tmp_path / "codeql"
        binary.touch()
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        assert _is_bundle_install() is False


# ===================================================================
# _codeql_search_path
# ===================================================================


class TestCodeqlSearchPath:
    """Tests for _codeql_search_path() helper."""

    def test_empty_for_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bundle installs return [] (auto-discovery)."""
        binary = tmp_path / "codeql"
        binary.touch()
        (tmp_path / "qlpacks" / "codeql" / "cpp-all").mkdir(parents=True)
        monkeypatch.setenv("CODEQL_HOME", str(tmp_path))
        monkeypatch.delenv("CODEQL_REPO", raising=False)
        assert _codeql_search_path() == []

    def test_codeql_repo_respected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CODEQL_REPO should be added if directory exists."""
        monkeypatch.delenv("CODEQL_HOME", raising=False)
        monkeypatch.setenv("CODEQL_REPO", str(tmp_path))
        with patch("cpp_analyzer._is_bundle_install", return_value=False):
            paths = _codeql_search_path()
            assert len(paths) == 1
            assert paths[0] == tmp_path.resolve()

    def test_empty_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODEQL_HOME", raising=False)
        monkeypatch.delenv("CODEQL_REPO", raising=False)
        with patch("cpp_analyzer._is_bundle_install", return_value=False):
            assert _codeql_search_path() == []


# ===================================================================
# CppAnalyzer class
# ===================================================================


class TestCppAnalyzer:
    """Tests for the CppAnalyzer class."""

    def test_language_attribute(self) -> None:
        analyzer = CppAnalyzer()
        assert analyzer.language == "cpp"

    def test_get_codeql_queries_finds_existing(self) -> None:
        """Should return at least list_functions.ql if it exists."""
        analyzer = CppAnalyzer()
        queries = analyzer.get_codeql_queries()
        # The .ql files exist in the repository
        assert len(queries) >= 1
        assert any("list_functions" in str(q) for q in queries)

    def test_get_codeql_queries_all_files(self) -> None:
        """Should return 4 queries: list_functions, api_functions, fuzz_targets, parameter_semantics."""
        analyzer = CppAnalyzer()
        queries = analyzer.get_codeql_queries()
        names = [q.stem for q in queries]
        for expected in ("list_functions", "api_functions", "fuzz_targets", "parameter_semantics"):
            assert expected in names, f"Missing query: {expected}"

    def test_get_compiler_flags(self) -> None:
        analyzer = CppAnalyzer()
        flags = analyzer.get_compiler_flags()
        assert isinstance(flags, list)
        assert len(flags) >= 1
        assert "-fsanitize=fuzzer" in flags
        assert "-g" in flags

    def test_extract_usage_contexts_returns_empty(self) -> None:
        """extract_usage_contexts is not implemented yet; returns []."""
        analyzer = CppAnalyzer()
        result = analyzer.extract_usage_contexts(Path("/tmp/fake-db"))
        assert result == []

    def test_generate_harness_template(self) -> None:
        analyzer = CppAnalyzer()
        func = FunctionInfo(
            name="parse_input",
            signature="int parse_input(const char* buf, int len)",
            return_type="int",
            parameters=["const char* buf", "int len"],
            file_path="parser.c",
            line=10,
        )
        template = analyzer.generate_harness_template(func)
        assert "parse_input" in template
        assert "LLVMFuzzerTestOneInput" in template

    def test_generate_harness_template_different_function(self) -> None:
        analyzer = CppAnalyzer()
        func = FunctionInfo(name="do_stuff", signature="void do_stuff()")
        template = analyzer.generate_harness_template(func)
        assert "do_stuff" in template
        assert "LLVMFuzzerTestOneInput" in template


# ===================================================================
# extract_functions — mocked subprocess
# ===================================================================


class TestExtractFunctions:
    """Tests for CppAnalyzer.extract_functions with mocked subprocess."""

    def _make_bqrs_tree(self, db_path: Path, bqrs_map: dict[str, bytes]) -> None:
        """Create fake BQRS files under db_path/results/."""
        results_dir = db_path / "results"
        for rel_path, content in bqrs_map.items():
            bqrs_file = results_dir / rel_path
            bqrs_file.parent.mkdir(parents=True, exist_ok=True)
            bqrs_file.write_bytes(content)

    def test_returns_empty_when_run_queries_fails(self, tmp_path: Path) -> None:
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()
        with patch.object(analyzer._runner, "run_queries", return_value=_completed(1, stderr=b"error")):
            result = analyzer.extract_functions(db)
        assert result == []

    def test_returns_empty_when_no_bqrs(self, tmp_path: Path) -> None:
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()
        # run_queries succeeds but no BQRS produced
        with patch.object(analyzer._runner, "run_queries", return_value=_completed(0)):
            result = analyzer.extract_functions(db)
        assert result == []

    def test_parses_list_functions_csv(self, tmp_path: Path) -> None:
        """Test that list_functions BQRS is decoded and parsed into FunctionInfo."""
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()

        csv_text = textwrap.dedent("""\
            src/parser.c,42,parse_data,parse_data,int,,const char* data\\, size_t size
            src/util.c,10,helper,,void,,
        """)

        self._make_bqrs_tree(db, {"list_functions/results.bqrs": b"fake-bqrs"})

        def mock_run_queries(*args, **kwargs):
            return _completed(0)

        def mock_subprocess_run(cmd, **kwargs):
            if "bqrs" in cmd and "decode" in cmd:
                return _completed(0, stdout=csv_text.encode())
            return _completed(1)

        with patch.object(analyzer._runner, "run_queries", side_effect=mock_run_queries):
            with patch("cpp_analyzer.subprocess.run", side_effect=mock_subprocess_run):
                result = analyzer.extract_functions(db)

        assert len(result) == 2
        assert result[0].name == "parse_data"
        assert result[0].file_path == "src/parser.c"
        assert result[0].line == 42
        assert result[0].return_type == "int"
        assert result[1].name == "helper"
        assert result[1].file_path == "src/util.c"

    def test_merges_api_and_fuzz_flags(self, tmp_path: Path) -> None:
        """Functions in api_functions and fuzz_targets get is_api/is_fuzz_target_candidate set."""
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()

        list_csv = "src/a.c,1,foo,foo,int,,\n"
        api_csv = "src/a.c,1,foo,api_foo\n"
        fuzz_csv = "src/a.c,1,foo,fuzz_foo\n"

        self._make_bqrs_tree(db, {
            "list_functions/results.bqrs": b"fake",
            "api_functions/results.bqrs": b"fake",
            "fuzz_targets/results.bqrs": b"fake",
        })

        call_count = {"n": 0}
        csv_responses = [list_csv, api_csv, fuzz_csv]

        def mock_subprocess_run(cmd, **kwargs):
            if "bqrs" in cmd and "decode" in cmd:
                idx = min(call_count["n"], len(csv_responses) - 1)
                call_count["n"] += 1
                return _completed(0, stdout=csv_responses[idx].encode())
            return _completed(1)

        with patch.object(analyzer._runner, "run_queries", return_value=_completed(0)):
            with patch("cpp_analyzer.subprocess.run", side_effect=mock_subprocess_run):
                result = analyzer.extract_functions(db)

        assert len(result) == 1
        assert result[0].is_api is True
        assert result[0].is_fuzz_target_candidate is True

    def test_merges_parameter_semantics(self, tmp_path: Path) -> None:
        """Parameter semantics from the parameter_semantics query get merged."""
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()

        list_csv = 'src/a.c,1,foo,foo,int,,"const char* data, size_t size"\n'
        sem_csv = "src/a.c,1,foo,0,BUFFER\nsrc/a.c,1,foo,1,SIZE\n"

        self._make_bqrs_tree(db, {
            "list_functions/results.bqrs": b"fake",
            "parameter_semantics/results.bqrs": b"fake",
        })

        call_count = {"n": 0}
        csv_responses = [list_csv, sem_csv]

        def mock_subprocess_run(cmd, **kwargs):
            if "bqrs" in cmd and "decode" in cmd:
                idx = min(call_count["n"], len(csv_responses) - 1)
                call_count["n"] += 1
                return _completed(0, stdout=csv_responses[idx].encode())
            return _completed(1)

        with patch.object(analyzer._runner, "run_queries", return_value=_completed(0)):
            with patch("cpp_analyzer.subprocess.run", side_effect=mock_subprocess_run):
                result = analyzer.extract_functions(db)

        assert len(result) == 1
        assert result[0].parameter_semantics == ["BUFFER", "SIZE"]

    def test_handles_invalid_csv_rows_gracefully(self, tmp_path: Path) -> None:
        """Short/malformed rows should be skipped without error."""
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()

        csv_text = "a,b\nsrc/a.c,1,foo,foo,int,,\n\n"

        self._make_bqrs_tree(db, {"list_functions/results.bqrs": b"fake"})

        def mock_subprocess_run(cmd, **kwargs):
            if "bqrs" in cmd and "decode" in cmd:
                return _completed(0, stdout=csv_text.encode())
            return _completed(1)

        with patch.object(analyzer._runner, "run_queries", return_value=_completed(0)):
            with patch("cpp_analyzer.subprocess.run", side_effect=mock_subprocess_run):
                result = analyzer.extract_functions(db)

        # Only the valid row should be parsed
        assert len(result) == 1
        assert result[0].name == "foo"

    def test_handles_non_numeric_line_gracefully(self, tmp_path: Path) -> None:
        """Non-numeric line numbers should default to 0."""
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()

        csv_text = "src/a.c,not_a_number,foo,foo,void,,\n"

        self._make_bqrs_tree(db, {"list_functions/results.bqrs": b"fake"})

        def mock_subprocess_run(cmd, **kwargs):
            if "bqrs" in cmd and "decode" in cmd:
                return _completed(0, stdout=csv_text.encode())
            return _completed(1)

        with patch.object(analyzer._runner, "run_queries", return_value=_completed(0)):
            with patch("cpp_analyzer.subprocess.run", side_effect=mock_subprocess_run):
                result = analyzer.extract_functions(db)

        assert len(result) == 1
        assert result[0].line == 0

    def test_returns_empty_when_no_queries_found(self, tmp_path: Path) -> None:
        """If no .ql files exist at the expected paths, return []."""
        analyzer = CppAnalyzer()
        # Override query paths to non-existent locations
        analyzer._list_functions_ql = tmp_path / "missing.ql"
        analyzer._api_functions_ql = tmp_path / "missing2.ql"
        analyzer._fuzz_targets_ql = tmp_path / "missing3.ql"
        analyzer._parameter_semantics_ql = tmp_path / "missing4.ql"

        result = analyzer.extract_functions(tmp_path / "db")
        assert result == []

    def test_codeql_resolve_module_error_logged(self, tmp_path: Path) -> None:
        """When stderr contains 'could not resolve module cpp', extra warning is logged."""
        analyzer = CppAnalyzer()
        db = tmp_path / "codeql-db"
        db.mkdir()

        error_msg = b"could not resolve module cpp"
        with patch.object(analyzer._runner, "run_queries", return_value=_completed(1, stderr=error_msg)):
            result = analyzer.extract_functions(db)
        assert result == []


# ===================================================================
# register() function
# ===================================================================


class TestRegister:
    """Tests for the register() plugin entry point."""

    def test_register_adds_cpp_language(self) -> None:
        registry = ComponentRegistry()
        register(registry)
        avail = registry.list_available()
        assert "cpp" in avail.get("language_analyzers", [])

    def test_registered_analyzer_is_cpp(self) -> None:
        registry = ComponentRegistry()
        register(registry)
        analyzer = registry.get_language("cpp")
        assert analyzer.language == "cpp"

    def test_registered_analyzer_has_required_methods(self) -> None:
        registry = ComponentRegistry()
        register(registry)
        analyzer = registry.get_language("cpp")
        assert callable(getattr(analyzer, "extract_functions", None))
        assert callable(getattr(analyzer, "extract_usage_contexts", None))
        assert callable(getattr(analyzer, "generate_harness_template", None))
        assert callable(getattr(analyzer, "get_codeql_queries", None))
        assert callable(getattr(analyzer, "get_compiler_flags", None))

    def test_double_register_overwrites(self) -> None:
        """Registering twice should overwrite (no crash)."""
        registry = ComponentRegistry()
        register(registry)
        register(registry)
        analyzer = registry.get_language("cpp")
        assert analyzer.language == "cpp"
