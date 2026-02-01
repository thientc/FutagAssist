"""CodeQL runner: run queries against a CodeQL database."""

from __future__ import annotations

import subprocess
from pathlib import Path


class CodeQLRunner:
    """Run CodeQL queries against a database."""

    def __init__(self, codeql_bin: str | Path = "codeql") -> None:
        self._codeql_bin = str(codeql_bin)

    def run_queries(
        self,
        db_path: Path,
        query_paths: list[Path],
        *,
        threads: int | None = None,
        timeout: int = 600,
        search_path: Path | list[Path] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """
        Run one or more CodeQL queries against the database.

        Uses: codeql database run-queries [options] -- <database> <query>...

        Results are written into the database results directory; use bqrs decode
        or database interpret-results to read them. Returns the completed process.

        search_path: Directory (or list of dirs) where CodeQL finds QL packs (e.g. the
        CodeQL bundle root containing qlpacks/). Required for standalone .ql files that
        import language modules (e.g. cpp). Use the extraction root of the CodeQL
        bundle (see BUILD_WITH_CODEQL.md).
        """
        db_path = Path(db_path).resolve()
        if not db_path.is_dir():
            raise FileNotFoundError(f"CodeQL database not found: {db_path}")

        args = [
            self._codeql_bin,
            "database",
            "run-queries",
        ]
        if search_path is not None:
            paths = [search_path] if isinstance(search_path, Path) else list(search_path)
            path_str = ":".join(str(Path(p).resolve()) for p in paths if Path(p).exists())
            if path_str:
                args.append(f"--search-path={path_str}")
        if threads is not None:
            args.append(f"--threads={threads}")
        args.append("--")
        args.append(str(db_path))
        for q in query_paths:
            p = Path(q)
            if not p.exists():
                raise FileNotFoundError(f"Query path not found: {p}")
            args.append(str(p.resolve()))

        return subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
        )
