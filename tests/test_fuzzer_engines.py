"""Tests for fuzzer engine plugins (libFuzzer, AFL++)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import CoverageReport, CrashInfo, FuzzResult


# ---------------------------------------------------------------------------
# libFuzzer engine
# ---------------------------------------------------------------------------


class TestLibFuzzerEngine:
    def test_register(self) -> None:
        from plugins.fuzzer.libfuzzer_engine import register
        reg = ComponentRegistry()
        register(reg)
        assert "libfuzzer" in reg.list_available()["fuzzer_engines"]

    def test_fuzz_success(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        binary = tmp_path / "fuzz_test"
        binary.write_bytes(b"\x7fELF")
        corpus = tmp_path / "corpus"
        corpus.mkdir()

        engine = LibFuzzerEngine()
        mock_result = MagicMock(
            returncode=0,
            stderr="Done 1000 runs in 10 second\nexec/s: 100\n",
            stdout="",
        )
        with patch("subprocess.run", return_value=mock_result):
            result = engine.fuzz(binary, corpus, max_total_time=10)

        assert isinstance(result, FuzzResult)
        assert result.success is True
        assert result.duration_seconds == 10.0
        assert result.execs_per_sec == 100.0

    def test_fuzz_crash_found(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        engine = LibFuzzerEngine()
        mock_result = MagicMock(returncode=1, stderr="exec/s: 50", stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = engine.fuzz(tmp_path / "bin", tmp_path / "corpus")

        assert result.success is True  # exit 1 = crash found, still "success"

    def test_fuzz_timeout(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        engine = LibFuzzerEngine()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 90)):
            result = engine.fuzz(tmp_path / "bin", tmp_path / "corpus", max_total_time=60)

        assert result.success is False

    def test_fuzz_binary_not_found(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        engine = LibFuzzerEngine()
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            result = engine.fuzz(tmp_path / "missing", tmp_path / "corpus")

        assert result.success is False

    def test_parse_crashes(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "crash-abc123").write_bytes(b"\x00")
        (artifacts / "leak-def456").write_bytes(b"\x00")
        (artifacts / "timeout-ghi789").write_bytes(b"\x00")
        (artifacts / "oom-jkl").write_bytes(b"\x00")
        (artifacts / "normal_file.txt").write_text("not a crash")

        engine = LibFuzzerEngine()
        crashes = engine.parse_crashes(artifacts)

        assert len(crashes) == 4
        classes = {c.warn_class for c in crashes}
        assert classes == {"CRASH", "LEAK", "TIMEOUT", "OOM"}

    def test_parse_crashes_empty_dir(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        empty = tmp_path / "empty"
        empty.mkdir()
        engine = LibFuzzerEngine()
        assert engine.parse_crashes(empty) == []

    def test_parse_crashes_nonexistent(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        engine = LibFuzzerEngine()
        assert engine.parse_crashes(tmp_path / "nonexistent") == []

    def test_get_coverage_no_profdata(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        engine = LibFuzzerEngine()
        cov = engine.get_coverage(tmp_path / "binary", tmp_path / "default.profdata")
        assert isinstance(cov, CoverageReport)
        assert cov.lines_total == 0

    def test_get_coverage_merges_profraw(self, tmp_path: Path) -> None:
        from plugins.fuzzer.libfuzzer_engine import LibFuzzerEngine

        profraw = tmp_path / "default.profraw"
        profraw.write_bytes(b"raw")
        profdata = tmp_path / "default.profdata"

        engine = LibFuzzerEngine()
        with patch("subprocess.run") as mock_run:
            # First call: profdata merge; second: llvm-cov export
            mock_run.side_effect = [
                MagicMock(returncode=0),  # merge
                MagicMock(returncode=1, stdout=""),  # export fails
            ]
            cov = engine.get_coverage(tmp_path / "binary", profdata)

        assert isinstance(cov, CoverageReport)


class TestLibFuzzerHelpers:
    def test_parse_duration(self) -> None:
        from plugins.fuzzer.libfuzzer_engine import _parse_duration
        assert _parse_duration("Done 5000 runs in 42 second") == 42.0
        assert _parse_duration("no match") == 0.0

    def test_parse_execs_per_sec(self) -> None:
        from plugins.fuzzer.libfuzzer_engine import _parse_execs_per_sec
        assert _parse_execs_per_sec("exec/s: 1234\nexec/s: 5678") == 5678.0
        assert _parse_execs_per_sec("no match") == 0.0


# ---------------------------------------------------------------------------
# AFL++ engine
# ---------------------------------------------------------------------------


class TestAFLPlusPlusEngine:
    def test_register(self) -> None:
        from plugins.fuzzer.aflpp_engine import register
        reg = ComponentRegistry()
        register(reg)
        assert "aflpp" in reg.list_available()["fuzzer_engines"]

    def test_fuzz_success(self, tmp_path: Path) -> None:
        from plugins.fuzzer.aflpp_engine import AFLPlusPlusEngine

        binary = tmp_path / "fuzz_test"
        binary.write_bytes(b"\x7fELF")
        corpus = tmp_path / "corpus"
        corpus.mkdir()

        engine = AFLPlusPlusEngine()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = engine.fuzz(binary, corpus, max_total_time=10)

        assert result.success is True
        # Verify seed was created
        assert any(corpus.iterdir())

    def test_fuzz_timeout(self, tmp_path: Path) -> None:
        from plugins.fuzzer.aflpp_engine import AFLPlusPlusEngine

        engine = AFLPlusPlusEngine()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            result = engine.fuzz(tmp_path / "bin", tmp_path / "corpus")

        assert result.success is False

    def test_fuzz_not_found(self, tmp_path: Path) -> None:
        from plugins.fuzzer.aflpp_engine import AFLPlusPlusEngine

        engine = AFLPlusPlusEngine()
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            result = engine.fuzz(tmp_path / "bin", tmp_path / "corpus")

        assert result.success is False

    def test_parse_crashes_afl_layout(self, tmp_path: Path) -> None:
        from plugins.fuzzer.aflpp_engine import AFLPlusPlusEngine

        crash_dir = tmp_path / "default" / "crashes"
        crash_dir.mkdir(parents=True)
        (crash_dir / "id:000000,sig:06,src:000000,time:123").write_bytes(b"\x00")
        (crash_dir / "id:000001,sig:11,src:000001,time:456").write_bytes(b"\x00")
        (crash_dir / "README.txt").write_text("AFL++ readme")

        engine = AFLPlusPlusEngine()
        crashes = engine.parse_crashes(tmp_path)

        assert len(crashes) == 2
        assert all(c.warn_class == "CRASH" for c in crashes)

    def test_parse_crashes_empty(self, tmp_path: Path) -> None:
        from plugins.fuzzer.aflpp_engine import AFLPlusPlusEngine

        engine = AFLPlusPlusEngine()
        assert engine.parse_crashes(tmp_path / "nonexistent") == []

    def test_get_coverage_returns_empty(self, tmp_path: Path) -> None:
        from plugins.fuzzer.aflpp_engine import AFLPlusPlusEngine

        engine = AFLPlusPlusEngine()
        cov = engine.get_coverage(tmp_path / "bin", tmp_path / "prof")
        assert isinstance(cov, CoverageReport)
        assert cov.lines_total == 0
