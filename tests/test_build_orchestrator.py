"""Tests for BuildOrchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from futagassist.build.build_orchestrator import BuildOrchestrator
from futagassist.build.readme_analyzer import ReadmeAnalyzer


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
    """_format_failure_message includes error output and LLM suggestion when LLM present."""
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
    assert "LLM suggestion" in msg


def test_build_orchestrator_format_failure_message_none_suggestion() -> None:
    """_format_failure_message includes 'none' when LLM suggests no fix."""
    class MockLLM:
        name = "mock"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    msg = orch._format_failure_message(
        error_output="err",
        build_cmd="make",
        llm_suggestion=None,
    )
    assert "none" in msg.lower() or "no fix" in msg.lower()


def test_build_orchestrator_ask_llm_for_fix_no_llm_returns_none() -> None:
    """_ask_llm_for_fix returns None when no LLM configured."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=None)
    assert orch._ask_llm_for_fix("make", "error") is None


def test_build_orchestrator_ask_llm_for_fix_returns_command() -> None:
    """_ask_llm_for_fix returns parsed command when LLM returns one."""
    class MockLLM:
        name = "mock"
        def complete(self, prompt: str, **kwargs): return "apt install cmake"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    fix = orch._ask_llm_for_fix("make", "error")
    assert fix == "apt install cmake"


def test_build_orchestrator_ask_llm_for_fix_none_returns_none() -> None:
    """_ask_llm_for_fix returns None when LLM returns 'none'."""
    class MockLLM:
        name = "mock"
        def complete(self, prompt: str, **kwargs): return "none"

    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, llm_provider=MockLLM())
    assert orch._ask_llm_for_fix("make", "error") is None


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
    success, db_path, message = orch.build(tmp_path, build_script="nonexistent.sh")
    assert success is False
    assert db_path is None
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
        success, db_path, message = orch.build(tmp_path, build_script=str(custom_script))
    assert success is True
    assert db_path is not None
    # CodeQL was called with the custom script path as --command
    call_args = m.call_args[0][0]
    assert str(custom_script) in call_args or custom_script.name in str(call_args)


def test_build_orchestrator_nonexistent_repo() -> None:
    """Non-existent repo returns failure."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")
    success, db_path, message = orch.build(Path("/nonexistent/repo"))
    assert success is False
    assert db_path is None
    assert "Not a directory" in message or "nonexistent" in message.lower()


def test_build_orchestrator_codeql_not_found(tmp_path: Path) -> None:
    """When codeql binary is not found, build fails with clear message."""
    (tmp_path / "README").write_text("make")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(
        readme_analyzer=analyzer,
        codeql_bin="/nonexistent/codeql",
    )
    success, db_path, message = orch.build(tmp_path)
    assert success is False
    assert db_path is None
    assert "not found" in message.lower() or "CodeQL" in message or "nonexistent" in message.lower()


def test_build_orchestrator_returns_db_path_on_success(tmp_path: Path) -> None:
    """When codeql succeeds (mocked), returns success and db_path."""
    (tmp_path / "README").write_text("make")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    orch = BuildOrchestrator(readme_analyzer=analyzer, codeql_bin="codeql")

    with patch("subprocess.run") as m:
        m.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        success, db_path, message = orch.build(tmp_path)

    assert success is True
    assert db_path is not None
    assert Path(db_path).name == "codeql-db" or "codeql" in str(db_path)
    assert message == ""
