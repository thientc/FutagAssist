"""Run build with CodeQL wrapper and LLM-assisted error recovery."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from futagassist.build.build_log import get_logger
from futagassist.build.codeql_injector import build_command_to_shell, codeql_database_create_args
from futagassist.build.readme_analyzer import ReadmeAnalyzer


FIX_PROMPT = """The build failed with the following output. Suggest a single shell command to fix the environment, to be run from the project root.

Rules:
- For autotools/libtool errors (LT_PATH_LD, LT_INIT, ltmain.sh not found, "command not found" from configure): the fix is to regenerate the build system, not install packages. Suggest: libtoolize && autoreconf -fi
- For missing compilers or system libs (e.g. "gcc: command not found", "No such file", missing -dev packages): suggest apt-get install of the missing package.
- If no fix is possible, reply with exactly: none

Build command: {build_cmd}

Error output:
---
{error_output}
---

Single fix command or "none":"""


class BuildOrchestrator:
    """Run CodeQL database creation with build command; on failure, ask LLM for fix and retry."""

    def __init__(
        self,
        readme_analyzer: ReadmeAnalyzer,
        llm_provider=None,
        codeql_bin: str | Path = "codeql",
        max_retries: int = 3,
    ) -> None:
        self._analyzer = readme_analyzer
        self._llm = llm_provider
        self._codeql_bin = str(codeql_bin)
        self._max_retries = max_retries

    def build(
        self,
        repo_path: Path,
        db_path: Path | None = None,
        language: str = "cpp",
        overwrite: bool = False,
        install_prefix: str | Path | None = None,
        build_script: str | Path | None = None,
    ) -> tuple[bool, Path | None, str, str | None]:
        """
        Run build with CodeQL wrapper. Returns (success, db_path or None, message, suggested_fix_cmd or None).
        If db_path is None, uses repo_path / "codeql-db".
        If install_prefix is set, build commands use that prefix and run make/ninja install
        so the library is installed to a custom folder for a future linking stage.
        If build_script is set, that script is run with CodeQL instead of auto-extracted
        build commands; path is resolved relative to repo_path if not absolute.
        """
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return False, None, f"Not a directory: {repo_path}", None

        out_db = Path(db_path).resolve() if db_path else (repo_path / "codeql-db")
        out_db.mkdir(parents=True, exist_ok=True)

        log = get_logger()

        if build_script is not None:
            # Custom build script: resolve path (relative to repo), use as CodeQL command
            script_path = Path(build_script)
            if not script_path.is_absolute():
                script_path = (repo_path / script_path).resolve()
            if not script_path.is_file():
                return False, None, f"Build script not found or not a file: {script_path}", None
            command_for_codeql = str(script_path)
            full_build_cmd = f"custom script: {command_for_codeql}"
            use_temp_script = False
        else:
            build_commands = self._analyzer.extract_build_commands(
                repo_path, install_prefix=install_prefix
            )
            full_build_cmd = build_command_to_shell(build_commands, repo_path)
            use_temp_script = True

        log.info("=== CodeQL build ===")
        log.info("Full build command: %s", full_build_cmd)

        # When overwrite is set, run a clean step first so the rebuild is from a clean tree.
        if overwrite and build_script is None:
            clean_cmd = self._analyzer.extract_clean_command(repo_path)
            if clean_cmd:
                log.info("Overwrite requested: running clean first: %s", clean_cmd)
                try:
                    clean_result = subprocess.run(
                        clean_cmd,
                        shell=True,
                        cwd=str(repo_path),
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if clean_result.returncode == 0:
                        log.info("Clean succeeded (exit 0)")
                    else:
                        log.warning(
                            "Clean failed (exit %s); continuing with build. stderr: %s",
                            clean_result.returncode,
                            (clean_result.stderr or clean_result.stdout or "")[:500],
                        )
                except subprocess.TimeoutExpired:
                    log.warning("Clean timed out (120s); continuing with build")
                except Exception as e:
                    log.warning("Clean failed: %s; continuing with build", e)

        for attempt in range(self._max_retries):
            if use_temp_script:
                # CodeQL's runner splits --command by space and execs the first token;
                # use a wrapper script so the "command" is a single executable path.
                script_path = self._write_build_script(repo_path, full_build_cmd)
                command_for_codeql = script_path
            log.info("Attempt %s/%s: command %s", attempt + 1, self._max_retries, command_for_codeql)
            try:
                args = codeql_database_create_args(
                    command_for_codeql,
                    out_db,
                    language=language,
                    codeql_bin=self._codeql_bin,
                    source_root=repo_path,
                    overwrite=overwrite,
                )
                try:
                    log.debug("CodeQL command: %s", " ".join(args))
                    result = subprocess.run(
                        args,
                        cwd=str(repo_path),
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                except subprocess.TimeoutExpired:
                    log.error("Build timed out (600s)")
                    return False, None, "Build timed out (600s)", None
                except FileNotFoundError:
                    log.error("CodeQL binary not found: %s", self._codeql_bin)
                    return False, None, f"CodeQL binary not found: {self._codeql_bin}", None

                if result.returncode == 0:
                    log.info("CodeQL build succeeded (exit 0)")
                    return True, out_db, "", None

                # Combine stderr and stdout so the user sees the full CodeQL/build output
                error_output = "\n".join(
                    x.strip() for x in (result.stderr, result.stdout) if x and x.strip()
                ).strip() or f"Exit code {result.returncode}"
                log.warning("CodeQL build failed (exit %s)", result.returncode)
                log.info("Error output:\n---\n%s\n---", error_output[:3000] + ("..." if len(error_output) > 3000 else ""))

                fix_cmd, llm_error = self._ask_llm_for_fix(full_build_cmd, error_output)

                if attempt + 1 >= self._max_retries:
                    log.warning("Max retries reached; build failed")
                    msg = self._format_failure_message(
                        error_output, full_build_cmd, fix_cmd, llm_error=llm_error
                    )
                    return False, None, msg, fix_cmd if fix_cmd else None

                if fix_cmd:
                    log.info(
                        "Suggested fix (run manually if you agree): %s",
                        fix_cmd,
                    )
                    msg = self._format_failure_message(
                        error_output, full_build_cmd, fix_cmd, llm_error=llm_error
                    )
                    return False, None, msg, fix_cmd
                log.warning("No fix suggested; build failed")
                msg = self._format_failure_message(
                    error_output, full_build_cmd, fix_cmd, llm_error=llm_error
                )
                return False, None, msg, None
            finally:
                if use_temp_script:
                    try:
                        os.unlink(script_path)
                    except OSError:
                        pass

        return False, None, "Max retries exceeded", None

    def _write_build_script(self, work_dir: Path, full_build_cmd: str) -> str:
        """Write full_build_cmd to a temporary executable script; return its path."""
        fd, path = tempfile.mkstemp(prefix="futagassist_build_", suffix=".sh", dir=str(work_dir))
        try:
            os.write(fd, b"#!/bin/sh\nset -e\n")
            os.write(fd, full_build_cmd.encode("utf-8"))
            os.write(fd, b"\n")
        finally:
            os.close(fd)
        os.chmod(path, 0o755)
        return path

    def _format_failure_message(
        self,
        error_output: str,
        build_cmd: str,
        llm_suggestion: str | None,
        llm_error: str | None = None,
    ) -> str:
        """Build a clear failure message including build command, error output, and optional LLM suggestion or error."""
        lines = [
            f"Build command: {build_cmd!r}",
            "",
            "Error output:",
            "---",
            error_output,
            "---",
        ]
        if self._llm is not None:
            if llm_error:
                lines.append(f"LLM suggestion: request failed ({llm_error}). Check API key, network, and OPENAI_BASE_URL / LLM config.")
            elif llm_suggestion:
                lines.append(f"Suggested fix (run manually if you agree): {llm_suggestion!r}")
            # When LLM had no suggestion, do not add "LLM suggestion: none" — keep output focused on the error.
        return "\n".join(lines)

    def _ask_llm_for_fix(self, build_cmd: str, error_output: str) -> tuple[str | None, str | None]:
        """Ask LLM for a fix command; return (suggestion, error_message). error_message is set when the API call fails."""
        log = get_logger()
        if not self._llm:
            log.info("LLM fix: no LLM configured; skipping")
            return None, None
        try:
            prompt = FIX_PROMPT.format(build_cmd=build_cmd, error_output=error_output[:4000])
            log.info("LLM fix: asking for fix command")
            log.debug("LLM prompt (fix):\n%s", prompt[:2500] + ("..." if len(prompt) > 2500 else ""))
            out = self._llm.complete(prompt).strip().split("\n")[0].strip()
            log.debug("LLM response (fix): %s", out[:500] if out else "(empty)")
            if not out or out.lower() == "none":
                log.info("LLM fix: suggestion = none")
                return None, None
            if out.startswith("```"):
                out = re.sub(r"^```\w*\n?", "", out).strip()
            if out.endswith("```"):
                out = out.rsplit("```", 1)[0].strip()
            log.info("LLM fix suggestion: %s", out)
            return (out if out else None), None
        except Exception as e:
            err_msg = str(e)
            log.warning("LLM fix request failed: %s", err_msg)
            return None, err_msg

    def _run_fix_command(self, work_dir: Path, fix_cmd: str) -> bool:
        """Run the suggested fix command; return True if exit code 0."""
        log = get_logger()
        log.info("Running fix command: %s", fix_cmd)
        try:
            result = subprocess.run(
                fix_cmd,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            ok = result.returncode == 0
            if ok:
                log.info("Fix command succeeded (exit 0)")
            else:
                log.warning("Fix command failed (exit %s): stderr=%s", result.returncode, (result.stderr or "")[:500])
            return ok
        except Exception as e:
            log.warning("Fix command failed: %s", e)
            return False
