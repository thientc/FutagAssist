"""Build stage: create CodeQL database from repo."""

from __future__ import annotations

from pathlib import Path

from futagassist.build.build_log import build_log_context
from futagassist.build.build_orchestrator import BuildOrchestrator
from futagassist.build.readme_analyzer import ReadmeAnalyzer
from futagassist.core.schema import PipelineContext, StageResult
from futagassist.utils import get_llm_provider, get_registry_and_config


class BuildStage:
    """Pipeline stage that builds the project and creates a CodeQL database."""

    name = "build"
    depends_on: list[str] = []

    def execute(self, context: PipelineContext) -> StageResult:
        """Run build with CodeQL wrapper; set context.db_path on success."""
        repo_path = context.repo_path
        if repo_path is None:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="repo_path not set in context",
            )

        registry, config_manager, err = get_registry_and_config(context, self.name)
        if err:
            return err

        cfg = config_manager.config
        language = context.language or cfg.language
        codeql_bin = "codeql"
        if cfg.codeql_home:
            codeql_bin = str(Path(cfg.codeql_home) / "bin" / "codeql")

        llm = get_llm_provider(registry, config_manager)

        log_file = context.config.get("build_log_file")
        if log_file is None:
            log_file = Path(repo_path) / "futagassist-build.log"
        else:
            log_file = Path(log_file)
        verbose = context.config.get("build_verbose", False)

        with build_log_context(log_file, verbose=verbose) as log:
            log.info("=== Build stage started ===")
            log.info("repo_path=%s", repo_path)
            db_path = context.db_path or (Path(repo_path) / "codeql-db")
            log.info("db_path=%s", db_path)
            log.info("language=%s overwrite=%s", language, context.config.get("build_overwrite", False))
            build_script = context.config.get("build_script")
            if build_script is not None:
                build_script = Path(build_script)
                if not build_script.is_absolute():
                    build_script = Path(repo_path) / build_script
                build_script = str(build_script.resolve())
                log.info("build_script=%s (custom)", build_script)
            log.info("LLM configured=%s", llm is not None)

            analyzer = ReadmeAnalyzer(llm_provider=llm)
            orchestrator = BuildOrchestrator(
                readme_analyzer=analyzer,
                llm_provider=llm,
                codeql_bin=codeql_bin,
                max_retries=cfg.llm.max_retries,
            )

            overwrite = context.config.get("build_overwrite", False)
            configure_options = context.config.get("build_configure_options")
            success, result_db, message, suggested_fix_cmd = orchestrator.build(
                repo_path=Path(repo_path),
                db_path=Path(db_path) if db_path else None,
                language=language,
                overwrite=overwrite,
                install_prefix=None,
                build_script=build_script,
                configure_options=configure_options,
            )

            if success and result_db is not None:
                log.info("=== Build stage finished: success ===")
                log.info("CodeQL database: %s", result_db)
                data: dict = {
                    "db_path": result_db,
                    "build_log_file": str(log_file),
                }
                return StageResult(
                    stage_name=self.name,
                    success=True,
                    data=data,
                )

            log.warning("=== Build stage finished: failed ===")
            if message:
                # Log full failure message so the log file contains the actual error (e.g. "./configure: not found")
                log.warning("message:\n%s", message)

        # Include hint when no LLM was used (no fix suggestions attempted)
        if llm is None and message:
            message = (
                message
                + "\n\n(No LLM configured: add an LLM plugin and set OPENAI_API_KEY or LLM_PROVIDER in .env for automatic fix suggestions.)"
            )
        fail_data: dict = {
            "build_log_file": str(log_file),
        }
        if suggested_fix_cmd is not None:
            fail_data["suggested_fix_command"] = suggested_fix_cmd
        return StageResult(
            stage_name=self.name,
            success=False,
            message=message or "Build failed",
            data=fail_data,
        )

    def can_skip(self, context: PipelineContext) -> bool:
        """Skip if db_path already set and exists."""
        if context.db_path is None:
            return False
        return Path(context.db_path).exists()
