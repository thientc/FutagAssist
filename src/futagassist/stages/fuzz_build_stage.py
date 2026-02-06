"""Fuzz Build stage: build library with debug + sanitizers and install to fuzz prefix."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from futagassist.build.build_log import build_log_context
from futagassist.build.build_orchestrator import _inject_configure_options
from futagassist.build.codeql_injector import build_command_to_shell
from futagassist.build.readme_analyzer import ReadmeAnalyzer
from futagassist.core.schema import PipelineContext, StageResult

FUZZ_CFLAGS = "-g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer"
FUZZ_CXXFLAGS = FUZZ_CFLAGS
FUZZ_LDFLAGS = "-fsanitize=address,undefined -fno-omit-frame-pointer"


class FuzzBuildStage:
    """Pipeline stage that builds the library with debug and sanitizers and installs to fuzz prefix."""

    name = "fuzz_build"
    depends_on: list[str] = ["build"]

    def execute(self, context: PipelineContext) -> StageResult:
        """Run plain build (no CodeQL) with sanitizer flags; set context.fuzz_install_prefix on success."""
        repo_path = context.repo_path
        if repo_path is None:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="repo_path not set in context",
            )
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"repo_path is not a directory: {repo_path}",
            )

        fuzz_prefix = context.config.get("fuzz_install_prefix")
        if fuzz_prefix is None:
            fuzz_prefix = repo_path / "install-fuzz"
        else:
            fuzz_prefix = Path(fuzz_prefix).resolve()

        log_file = context.config.get("fuzz_build_log_file")
        if log_file is None:
            log_file = repo_path / "futagassist-fuzz-build.log"
        else:
            log_file = Path(log_file)
        verbose = context.config.get("fuzz_build_verbose", False)
        configure_options = context.config.get("fuzz_build_configure_options")

        with build_log_context(log_file, verbose=verbose) as log:
            log.info("=== Fuzz Build stage started ===")
            log.info("repo_path=%s fuzz_install_prefix=%s", repo_path, fuzz_prefix)

            analyzer = ReadmeAnalyzer(llm_provider=None)
            build_commands = analyzer.extract_build_commands(
                repo_path, install_prefix=fuzz_prefix
            )
            if configure_options:
                build_commands = _inject_configure_options(build_commands, configure_options)
                log.info("Configure options applied: %s", configure_options.strip())
            full_cmd = build_command_to_shell(build_commands, repo_path)

            env = os.environ.copy()
            cfl = env.get("CFLAGS", "")
            env["CFLAGS"] = (cfl + " " + FUZZ_CFLAGS).strip() if cfl else FUZZ_CFLAGS
            cxxfl = env.get("CXXFLAGS", "")
            env["CXXFLAGS"] = (cxxfl + " " + FUZZ_CXXFLAGS).strip() if cxxfl else FUZZ_CXXFLAGS
            ldfl = env.get("LDFLAGS", "")
            env["LDFLAGS"] = (ldfl + " " + FUZZ_LDFLAGS).strip() if ldfl else FUZZ_LDFLAGS

            log.info("Full build command: %s", full_cmd)
            log.info("CFLAGS=%s CXXFLAGS=%s LDFLAGS=%s", env["CFLAGS"], env["CXXFLAGS"], env["LDFLAGS"])

            try:
                result = subprocess.run(
                    full_cmd,
                    shell=True,
                    cwd=str(repo_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
            except subprocess.TimeoutExpired:
                log.warning("Fuzz build timed out (600s)")
                return StageResult(
                    stage_name=self.name,
                    success=False,
                    message="Fuzz build timed out (600s)",
                    data={"fuzz_build_log_file": str(log_file)},
                )
            except Exception as e:
                log.warning("Fuzz build failed: %s", e)
                return StageResult(
                    stage_name=self.name,
                    success=False,
                    message=str(e),
                    data={"fuzz_build_log_file": str(log_file)},
                )

            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                if err:
                    log.warning("Fuzz build failed (exit %s):\n%s", result.returncode, err)
                return StageResult(
                    stage_name=self.name,
                    success=False,
                    message=f"Fuzz build failed (exit {result.returncode})",
                    data={
                        "fuzz_build_log_file": str(log_file),
                        "stderr": (result.stderr or "")[:8000],
                        "stdout": (result.stdout or "")[:8000],
                    },
                )

            log.info("=== Fuzz Build stage finished: success ===")
            log.info("Instrumented install: %s", fuzz_prefix)

        return StageResult(
            stage_name=self.name,
            success=True,
            data={
                "fuzz_install_prefix": str(fuzz_prefix),
                "fuzz_build_log_file": str(log_file),
            },
        )

    def can_skip(self, context: PipelineContext) -> bool:
        """Skip if fuzz_install_prefix already set and looks like a valid install (lib or include)."""
        prefix = context.fuzz_install_prefix or context.config.get("fuzz_install_prefix")
        if prefix is None:
            return False
        p = Path(prefix)
        if not p.is_dir():
            return False
        return (p / "lib").is_dir() or (p / "include").is_dir()
