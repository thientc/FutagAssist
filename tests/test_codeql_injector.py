"""Tests for CodeQL injector."""

from __future__ import annotations

from pathlib import Path

import pytest

from futagassist.build.codeql_injector import build_command_to_shell, codeql_database_create_args


def test_codeql_database_create_args() -> None:
    args = codeql_database_create_args(
        build_command='cd /repo && make',
        db_path=Path("/out/db"),
        language="cpp",
        codeql_bin="codeql",
    )
    assert args[0] == "codeql"
    assert "database" in args
    assert "create" in args
    assert "/out/db" in args or str(Path("/out/db")) in args
    assert "--language" in args
    assert "cpp" in args
    assert "--command" in args
    assert "make" in " ".join(args)


def test_codeql_database_create_args_with_source_root() -> None:
    args = codeql_database_create_args(
        build_command="make",
        db_path=Path("/db"),
        language="cpp",
        source_root=Path("/src"),
    )
    assert "--source-root" in args
    assert "/src" in str(args) or str(Path("/src")) in str(args)


def test_build_command_to_shell() -> None:
    work = Path("/repo")
    cmd = build_command_to_shell(["make"], work)
    assert "cd" in cmd
    assert "/repo" in cmd
    assert "make" in cmd


def test_build_command_to_shell_multiple() -> None:
    work = Path("/repo")
    cmd = build_command_to_shell(["mkdir build", "cd build", "cmake ..", "make"], work)
    assert "cd" in cmd
    assert "mkdir" in cmd
    assert "cmake" in cmd
    assert "make" in cmd


def test_codeql_database_create_args_overwrite() -> None:
    """When overwrite=True, --overwrite is in args."""
    args = codeql_database_create_args(
        build_command="make",
        db_path=Path("/db"),
        language="cpp",
        overwrite=True,
    )
    assert "--overwrite" in args


def test_build_command_to_shell_empty_list() -> None:
    """Empty build_commands list yields default 'cd work_dir && make'."""
    work = Path("/repo")
    cmd = build_command_to_shell([], work)
    assert "cd" in cmd
    assert "/repo" in cmd
    assert "make" in cmd
