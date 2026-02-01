"""Tests for BuildOrchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from futagassist.build.build_orchestrator import (
    BuildOrchestrator,
    _condense_error_for_llm,
    _inject_configure_options,
    _strip_log_envelope,
)
from futagassist.build.readme_analyzer import ReadmeAnalyzer


def test_strip_log_envelope_removes_datetime_and_channel() -> None:
    """_strip_log_envelope removes [timestamp] [build-stdout] / [build-stderr] / [ERROR] prefix."""
    assert _strip_log_envelope("[2026-02-01 23:48:15] [build-stdout] checking for gcc... gcc") == "checking for gcc... gcc"
    assert _strip_log_envelope("[2026-02-01 23:48:24] [build-stderr] configure: error: libpsl not found") == "configure: error: libpsl not found"
    assert _strip_log_envelope("[2026-02-01 23:48:24] [ERROR] Spawned process exited") == "Spawned process exited"
    assert _strip_log_envelope("A fatal error occurred: Exit status 1") == "A fatal error occurred: Exit status 1"


def test_condense_error_for_llm_keeps_errors_strips_envelope() -> None:
    """_condense_error_for_llm keeps error lines and build context, strips log envelope."""
    raw = """Initializing database at /path/codeql-db.
Running build command: [/path/build.sh]
A fatal error occurred: Exit status 1 from command: [/path/build.sh]
[2026-02-01 23:48:15] [build-stdout] checking for gcc... gcc
[2026-02-01 23:48:15] [build-stdout] checking whether the C compiler works... yes
[2026-02-01 23:48:24] [build-stderr] configure: error: libpsl libs and/or directories were not found where specified!
"""
    out = _condense_error_for_llm(raw, max_chars=2000)
    assert "Build failed (exit status 1)" in out
    assert "configure: error: libpsl" in out
    assert "libs and/or directories were not found" in out
    assert "[2026-02-01" not in out
    assert "[build-stdout]" not in out
    assert "[build-stderr]" not in out
    assert "checking for gcc" not in out


def test_inject_configure_options_append_to_configure_step() -> None:
    """_inject_configure_options appends options to the first ./configure step."""
    commands = ["./buildconf", "./configure", "make"]
    result = _inject_configure_options(commands, " --without-ssl ")
    assert result == ["./buildconf", "./configure --without-ssl", "make"]


def test_inject_configure_options_no_configure_unchanged() -> None:
    """When there is no configure step, list is unchanged."""
    commands = ["make"]
    result = _inject_configure_options(commands, "--without-ssl")
    assert result == ["make"]


def test_inject_configure_options_empty_opts_unchanged() -> None:
    """When configure_options is empty or whitespace, list is unchanged."""
    commands = ["./buildconf", "./configure", "make"]
    result = _inject_configure_options(commands, "")
    assert result == commands
    result = _inject_configure_options(commands, "   ")
    assert result == commands


def test_inject_configure_options_configure_with_existing_args() -> None:
    """Options are appended to configure even when it already has args (e.g. --prefix)."""
    commands = ["./configure --prefix=/opt", "make"]
    result = _inject_configure_options(commands, "--without-ssl")
    assert result == ["./configure --prefix=/opt --without-ssl", "make"]


def test_build_orchestrator_write_build_script_creates_executable(tmp_path: Path) -> None:
    """_write_build_script creates a script with shebang and build command."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    script_path = orch._write_build_script(tmp_path, "cd /x && make")
    assert Path(script_path).exists()
    content = Path(script_path).read_text()
    assert content.startswith("#!/bin/sh")
    assert "cd /x && make" in content
    assert Path(script_path).stat().st_mode & 0o111
    Path(script_path).unlink(missing_ok=True)


def test_build_orchestrator_format_failure_message_includes_llm_suggestion() -> None:
    """_format_failure_message includes error output and suggested fix (run manually) when LLM present."""
    class MockLLM:
        name = "mock"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    msg = orch._format_failure_message(
        error_output="exit 1",
        build_cmd="make",
        llm_suggestion="apt install foo",
    )
    assert "make" in msg
    assert "exit 1" in msg
    assert "apt install foo" in msg
    assert "Suggested fix (run manually if you agree)" in msg


def test_build_orchestrator_format_failure_message_none_suggestion() -> None:
    """_format_failure_message omits 'LLM suggestion: none' when LLM suggests no fix (keep output focused)."""
    class MockLLM:
        name = "mock"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    msg = orch._format_failure_message(
        error_output="err",
        build_cmd="make",
        llm_suggestion=None,
    )
    assert "Build command" in msg and "err" in msg
    assert "LLM suggestion: none" not in msg and "no fix suggested" not in msg


def test_build_orchestrator_format_failure_message_llm_error() -> None:
    """_format_failure_message includes LLM request error when API call failed."""
    class MockLLM:
        name = "mock"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    msg = orch._format_failure_message(
        error_output="err",
        build_cmd="make",
        llm_suggestion=None,
        llm_error="Connection error.",
    )
    assert "Connection error" in msg
    assert "request failed" in msg.lower() or "failed" in msg.lower()


def test_build_orchestrator_ask_llm_for_fix_no_llm_returns_none() -> None:
    """_ask_llm_for_fix returns (None, None) when no LLM configured."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=None)
    fix, err = orch._ask_llm_for_fix("make", "error")
    assert fix is None and err is None


def test_build_orchestrator_ask_llm_for_fix_returns_command() -> None:
    """_ask_llm_for_fix returns (parsed_command, None) when LLM returns one."""
    class MockLLM:
        name = "mock"
        def complete(self, prompt: str, **kwargs): return "apt install cmake"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    fix, err = orch._ask_llm_for_fix("make", "error")
    assert fix == "apt install cmake" and err is None


def test_build_orchestrator_ask_llm_for_fix_none_returns_none() -> None:
    """_ask_llm_for_fix returns (None, None) when LLM returns 'none'."""
    class MockLLM:
        name = "mock"
        def complete(self, prompt: str, **kwargs): return "none"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    fix, err = orch._ask_llm_for_fix("make", "error")
    assert fix is None and err is None


def test_build_orchestrator_run_fix_command_success(tmp_path: Path) -> None:
    """_run_fix_command returns True when command exits 0."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    assert orch._run_fix_command(tmp_path, "true") is True


def test_build_orchestrator_run_fix_command_failure(tmp_path: Path) -> None:
    """_run_fix_command returns False when command exits non-zero."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    assert orch._run_fix_command(tmp_path, "false") is False


def test_build_orchestrator_custom_build_script_not_found(tmp_path: Path) -> None:
    """When build_script is set but file does not exist, returns failure with clear message."""
    (tmp_path / "README").write_text("make")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    success, db_path, message, suggested_fix = orch.build(tmp_path, build_script="nonexistent.sh")
    assert success is False
    assert db_path is None
    assert suggested_fix is None
    assert "not found" in message.lower() or "Build script" in message


def test_build_orchestrator_custom_build_script_used(tmp_path: Path) -> None:
    """When build_script is set and exists, that script path is passed to CodeQL (mocked)."""
    custom_script = tmp_path / "mybuild.sh"
    custom_script.write_text("#!/bin/sh\nmake")
    custom_script.chmod(0o755)
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    with patch("subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        success, db_path, message, suggested_fix = orch.build(tmp_path, build_script=str(custom_script))
    assert success is True
    assert suggested_fix is None
    assert db_path is not None
    # CodeQL was called with the custom script path as --command
    call_args = m.call_args[0][0]
    assert str(custom_script) in call_args or custom_script.name in str(call_args)


def test_build_orchestrator_nonexistent_repo() -> None:
    """Non-existent repo returns failure."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    success, db_path, message, suggested_fix = orch.build(Path("/nonexistent/repo"))
    assert success is False
    assert db_path is None
    assert suggested_fix is None
    assert "Not a directory" in message or "nonexistent" in message.lower()


def test_build_orchestrator_codeql_not_found(tmp_path: Path) -> None:
    """When codeql binary is not found, build fails with clear message."""
    (tmp_path / "README").write_text("make")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(
        readme_analyzer=analyzer,
        codeql_bin="/nonexistent/codeql",
    )
    success, db_path, message, suggested_fix = orch.build(tmp_path)
    assert success is False
    assert db_path is None
    assert suggested_fix is None
    assert "not found" in message.lower() or "CodeQL" in message or "nonexistent" in message.lower()


def test_build_orchestrator_returns_db_path_on_success(tmp_path: Path) -> None:
    """When codeql succeeds (mocked), returns success and db_path."""
    (tmp_path / "README").write_text("make")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")

    with patch("subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        success, db_path, message, suggested_fix = orch.build(tmp_path)

    assert success is True
    assert db_path is not None
    assert suggested_fix is None
    assert Path(db_path).name == "codeql-db" or "codeql" in str(db_path)
    assert message == ""


def test_build_orchestrator_returns_suggested_fix_on_failure_with_fix(tmp_path: Path) -> None:
    """When build fails and LLM suggests a fix, fourth return value is the suggested command."""
    (tmp_path / "README").write_text("make")
    class MockLLM:
        name = "mock"
        def complete(self, prompt: str, **kwargs): return "libtoolize && autoreconf -fi"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM(), codeql_bin="codeql")
    with patch("subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "LT_PATH_LD: command not found"})()
        success, db_path, message, suggested_fix = orch.build(tmp_path)
    assert success is False
    assert db_path is None
    assert suggested_fix == "libtoolize && autoreconf -fi"
    assert "Suggested fix" in message or "libtoolize" in message


def test_build_orchestrator_configure_options_in_script(tmp_path: Path) -> None:
    """When configure_options is set, the build script contains ./configure <options>."""
    (tmp_path / "configure.ac").write_text("AC_INIT")
    (tmp_path / "Makefile.am").write_text("SUBDIRS = .")
    (tmp_path / "buildconf").write_text("#!/bin/sh\nautoreconf -fi")
    captured_cmd: list[str] = []
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    orig_write = orch._write_build_script

    def capture_script(work_dir: Path, full_build_cmd: str) -> str:
        captured_cmd.append(full_build_cmd)
        return orig_write(work_dir, full_build_cmd)

    orch._write_build_script = capture_script
    with patch("subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        success, _, _, _ = orch.build(tmp_path, configure_options="--without-ssl")
    assert success is True
    assert len(captured_cmd) == 1
    assert "./configure" in captured_cmd[0] and "--without-ssl" in captured_cmd[0]
