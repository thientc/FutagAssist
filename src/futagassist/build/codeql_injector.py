"""Wrap build command with CodeQL database create."""

from __future__ import annotations

import shlex
from pathlib import Path


def codeql_database_create_args(
    build_command: str,
    db_path: Path,
    language: str = "cpp",
    codeql_bin: str | Path = "codeql",
    source_root: Path | None = None,
    overwrite: bool = False,
) -> list[str]:
    """
    Build the argument list for `codeql database create`.
    The actual command will be: codeql database create <args>.
    build_command is executed from source_root (or db_path.parent) and should build the project.
    If overwrite is True, pass --overwrite so CodeQL overwrites an existing database directory.
    """
    db_path = Path(db_path).resolve()
    codeql_bin = str(codeql_bin)
    args = [
        codeql_bin,
        "database",
        "create",
        str(db_path),
        "--language",
        language,
        "--command",
        build_command,
    ]
    if source_root is not None:
        args.extend(["--source-root", str(Path(source_root).resolve())])
    if overwrite:
        args.append("--overwrite")
    return args


def build_command_to_shell(build_commands: list[str], work_dir: Path) -> str:
    """
    Turn a list of build command strings into a single shell command run from work_dir.
    Uses 'cd work_dir && cmd1 && cmd2 ...'.
    """
    work_dir = Path(work_dir).resolve()
    if not build_commands:
        return f"cd {shlex.quote(str(work_dir))} && make"
    return " && ".join(
        [f"cd {shlex.quote(str(work_dir))}"] + build_commands
    )
