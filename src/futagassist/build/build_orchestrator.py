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


# ---------------------------------------------------------------------------
# Named constants (avoid magic numbers)
# ---------------------------------------------------------------------------

#: Timeout (seconds) for the CodeQL build subprocess.
BUILD_TIMEOUT = 600

#: Timeout (seconds) for clean and fix commands.
AUX_COMMAND_TIMEOUT = 120

#: Max characters of error output sent to the LLM for fix suggestions.
MAX_LLM_ERROR_CHARS = 4000

#: Max characters of error output included in failure log messages.
MAX_LOG_ERROR_CHARS = 3000

#: Max characters of stderr shown in log warnings for auxiliary commands.
MAX_LOG_STDERR_CHARS = 500

#: Max characters of LLM prompt shown in debug logging.
MAX_LOG_PROMPT_CHARS = 2500

FIX_PROMPT = """The build failed with the following output. Suggest a single shell command to fix the environment, to be run from the project root.

Rules:
- If "./configure: not found" or "configure: not found" (exit 127) and the project has configure.ac: suggest generating configure first. If a file named "buildconf" exists: ./buildconf. Otherwise: autoreconf -fi (or libtoolize && autoreconf -fi).
- For other autotools/libtool errors (LT_PATH_LD, LT_INIT, ltmain.sh not found, "command not found" from configure): the fix is to regenerate the build system. Suggest: libtoolize && autoreconf -fi
- For missing compilers or system libs (e.g. "gcc: command not found", "No such file", missing -dev packages): suggest apt-get install of the missing package.
- For "libs and/or directories were not found", "was not found", "not found where specified" (configure): the missing library is usually named in the message (e.g. libpsl -> libpsl-dev). Suggest: apt-get install -y <package>-dev (e.g. libpsl-dev), or to skip the feature add a configure option like --without-<feature> if the project supports it.
- If no fix is possible, reply with exactly: none

Build command: {build_cmd}

Error output:
---
{error_output}
---

Single fix command or "none":"""

# Strip CodeQL log envelope: [YYYY-MM-DD HH:MM:SS] [build-stdout] or [build-stderr] or [ERROR]
_RE_LOG_PREFIX = re.compile(
    r"^\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\]\s*\[(?:build-stdout|build-stderr|ERROR)\]\s*"
)


def _strip_log_envelope(line: str) -> str:
    """Remove datetime and channel prefix (build-stdout, build-stderr, ERROR) from a log line."""
    return _RE_LOG_PREFIX.sub("", line).strip()


def _condense_error_for_llm(error_output: str, max_chars: int = MAX_LLM_ERROR_CHARS) -> str:
    """
    Produce a short summary for the LLM: strip log envelope (datetime, build-stdout/stderr),
    keep only basic build context and actual error lines (error, fatal, not found, failed, etc.).
    """
    lines = error_output.splitlines()
    summary_lines: list[str] = []
    exit_status: str | None = None

    # Keywords that indicate an error line (after stripping envelope)
    error_keywords = (
        "error",
        "Error",
        "fatal",
        "Fatal",
        "not found",
        "failed",
        "Failed",
        "undefined reference",
        "No such file",
        "cannot find",
        "were not found",
        "not found where",
        "No rule to make",
        "missing",
    )

    seen_fatal = False
    for raw_line in lines:
        line = _strip_log_envelope(raw_line)
        if not line:
            continue
        # Keep context: exit status from "A fatal error occurred: Exit status N" (once)
        if ("A fatal error occurred" in line or "Exit status" in line) and not seen_fatal:
            match = re.search(r"Exit status (\d+)", line, re.IGNORECASE)
            if match:
                exit_status = match.group(1)
            summary_lines.append("Build failed (exit status {}).".format(exit_status or "non-zero"))
            seen_fatal = True
            continue
        # Keep short context lines (no timestamp left)
        if line.startswith("Initializing database") or line.startswith("Running build command") or line.startswith("Running command in"):
            continue  # skip verbose context
        # Keep lines that look like errors
        if any(kw in line for kw in error_keywords):
            summary_lines.append(line)
            continue
        # Keep "configure: error:" style lines (configure script errors)
        if "configure:" in line and (":" in line):
            summary_lines.append(line)
            continue

    condensed = "\n".join(summary_lines)
    if not condensed.strip():
        # Fallback: strip envelope from all lines and take last N chars
        stripped = "\n".join(_strip_log_envelope(l) for l in lines if _strip_log_envelope(l))
        condensed = stripped[-max_chars:] if len(stripped) > max_chars else stripped
        if condensed != stripped:
            condensed = "(output truncated; showing last {} chars)\n{}".format(max_chars, condensed)
    elif len(condensed) > max_chars:
        condensed = "(output truncated; showing last {} chars)\n{}".format(
            max_chars, condensed[-max_chars:]
        )
    return condensed


def _inject_configure_options(build_commands: list[str], configure_options: str) -> list[str]:
    """
    Append configure_options to the first configure step in build_commands.
    Configure step: cmd.strip().startswith('./configure') or cmd.strip() == 'configure'.
    Returns a new list (does not mutate input).
    """
    opts = configure_options.strip()
    if not opts:
        return list(build_commands)
    result = list(build_commands)
    for i, cmd in enumerate(result):
        s = cmd.strip()
        if s.startswith("./configure") or s == "configure":
            result[i] = cmd + " " + opts
            return result
    return result


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
        configure_options: str | None = None,
    ) -> tuple[bool, Path | None, str, str | None]:
        """
        Run build with CodeQL wrapper. Returns (success, db_path or None, message, suggested_fix_cmd or None).
        If db_path is None, uses repo_path / "codeql-db".
        If install_prefix is set, build commands use that prefix and run make/ninja install
        so the library is installed to a custom folder for a future linking stage.
        If build_script is set, that script is run with CodeQL instead of auto-extracted
        build commands; path is resolved relative to repo_path if not absolute.
        If configure_options is set, extra flags are appended to the configure step (ignored when using build_script).
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
            if configure_options:
                build_commands = _inject_configure_options(build_commands, configure_options)
                log.info("Configure options applied: %s", configure_options.strip())
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
                        timeout=AUX_COMMAND_TIMEOUT,
                    )
                    if clean_result.returncode == 0:
                        log.info("Clean succeeded (exit 0)")
                    else:
                        log.warning(
                            "Clean failed (exit %s); continuing with build. stderr: %s",
                            clean_result.returncode,
                            (clean_result.stderr or clean_result.stdout or "")[:MAX_LOG_STDERR_CHARS],
                        )
                except subprocess.TimeoutExpired:
                    log.warning("Clean timed out (%ds); continuing with build", AUX_COMMAND_TIMEOUT)
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
                        timeout=BUILD_TIMEOUT,
                    )
                except subprocess.TimeoutExpired:
                    log.error("Build timed out (%ds)", BUILD_TIMEOUT)
                    return False, None, f"Build timed out ({BUILD_TIMEOUT}s)", None
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
                log.info("Error output:\n---\n%s\n---", error_output[:MAX_LOG_ERROR_CHARS] + ("..." if len(error_output) > MAX_LOG_ERROR_CHARS else ""))

                fix_cmd, llm_error = self._ask_llm_for_fix(full_build_cmd, error_output)

                if attempt + 1 >= self._max_retries:
                    log.warning("Max retries reached; build failed")
                    msg = self._format_failure_message(
                        error_output, full_build_cmd, fix_cmd, llm_error=llm_error
                    )
                    return False, None, msg, fix_cmd if fix_cmd else None

                if fix_cmd:
                    log.info("Attempting auto-fix: %s", fix_cmd)
                    if self._run_fix_command(repo_path, fix_cmd):
                        log.info("Fix succeeded; retrying build (attempt %s/%s)", attempt + 2, self._max_retries)
                        continue
                    else:
                        log.warning("Fix command failed; returning suggestion for manual retry")
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
            # Send only condensed error: strip datetime/build-stdout/build-stderr, keep error lines and basic context
            error_snippet = _condense_error_for_llm(error_output, max_chars=MAX_LLM_ERROR_CHARS)
            prompt = FIX_PROMPT.format(build_cmd=build_cmd, error_output=error_snippet)
            log.info("LLM fix: asking for fix command")
            log.debug("LLM prompt (fix):\n%s", prompt[:MAX_LOG_PROMPT_CHARS] + ("..." if len(prompt) > MAX_LOG_PROMPT_CHARS else ""))
            out = self._llm.complete(prompt).strip().split("\n")[0].strip()
            log.debug("LLM response (fix): %s", out[:MAX_LOG_STDERR_CHARS] if out else "(empty)")
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
                timeout=AUX_COMMAND_TIMEOUT,
            )
            ok = result.returncode == 0
            if ok:
                log.info("Fix command succeeded (exit 0)")
            else:
                log.warning("Fix command failed (exit %s): stderr=%s", result.returncode, (result.stderr or "")[:MAX_LOG_STDERR_CHARS])
            return ok
        except Exception as e:
            log.warning("Fix command failed: %s", e)
            return False
