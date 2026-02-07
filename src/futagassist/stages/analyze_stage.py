"""Analyze stage: extract function info from CodeQL database via LanguageAnalyzer."""

from __future__ import annotations

import logging
from pathlib import Path

from futagassist.analysis.context_builder import enrich_functions
from futagassist.analysis.llm_analyze import suggest_usage_contexts
from futagassist.core.schema import PipelineContext, StageResult
from futagassist.utils import get_llm_provider, get_registry_and_config

log = logging.getLogger(__name__)


class AnalyzeStage:
    """Pipeline stage that extracts function information from a CodeQL database."""

    name = "analyze"
    depends_on: list[str] = ["build"]

    def execute(self, context: PipelineContext) -> StageResult:
        """Run language analyzer to extract functions; optionally enrich context and export JSON."""
        db_path = context.db_path
        if db_path is None:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="db_path not set in context (run build stage first or pass --db).",
            )

        registry, config_manager, err = get_registry_and_config(context, self.name)
        if err:
            return err

        cfg = config_manager.config
        language = context.language or cfg.language
        avail = registry.list_available()
        if language not in avail.get("language_analyzers", []):
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"No language analyzer registered for '{language}'. "
                f"Available: {', '.join(avail.get('language_analyzers', [])) or 'none'}.",
            )

        analyzer = registry.get_language(language)
        db = Path(db_path)
        if not db.is_dir():
            return StageResult(
                stage_name=self.name,
                success=False,
                message=f"CodeQL database not found or not a directory: {db_path}",
            )

        functions = analyzer.extract_functions(db)
        usage_contexts = analyzer.extract_usage_contexts(db)

        if context.repo_path and functions:
            functions = enrich_functions(functions, context.repo_path)

        llm = get_llm_provider(registry, config_manager, avail=avail)

        if llm and functions:
            extra = suggest_usage_contexts(
                llm, functions, usage_contexts, context.repo_path
            )
            if extra:
                usage_contexts = list(usage_contexts) + extra
                log.info("LLM suggested %s additional usage context(s)", len(extra))
        else:
            if functions and not llm:
                log.debug("LLM analysis skipped (no LLM configured)")

        output_path = context.config.get("analyze_output")
        if output_path and "json" in avail.get("reporters", []):
            reporter = registry.get_reporter("json")
            path = Path(output_path)
            if hasattr(reporter, "report_analysis") and callable(getattr(reporter, "report_analysis")):
                reporter.report_analysis(functions, usage_contexts, path)
            elif functions:
                reporter.report_functions(functions, path)

        data: dict = {"functions": functions, "usage_contexts": usage_contexts}
        if output_path:
            data["analyze_output"] = str(output_path)
        return StageResult(
            stage_name=self.name,
            success=True,
            data=data,
        )

    def can_skip(self, context: PipelineContext) -> bool:
        """Do not skip; analysis is cheap and db may have changed."""
        return False
