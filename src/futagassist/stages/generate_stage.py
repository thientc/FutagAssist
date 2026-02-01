"""Generate stage: create fuzz harnesses from function info using templates and LLM."""

from __future__ import annotations

import logging
from pathlib import Path

from futagassist.core.schema import GeneratedHarness, PipelineContext, StageResult
from futagassist.generation.harness_generator import HarnessGenerator
from futagassist.generation.syntax_validator import SyntaxValidator

log = logging.getLogger(__name__)


class GenerateStage:
    """Pipeline stage that generates fuzz harnesses from analyzed functions."""

    name = "generate"
    depends_on: list[str] = ["analyze"]

    def execute(self, context: PipelineContext) -> StageResult:
        """Generate fuzz harnesses from functions and usage contexts."""
        functions = context.functions
        if not functions:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="No functions in context (run analyze stage first).",
            )

        registry = context.config.get("registry")
        config_manager = context.config.get("config_manager")
        if not registry or not config_manager:
            return StageResult(
                stage_name=self.name,
                success=False,
                message="registry or config_manager not set in context.config",
            )

        cfg = config_manager.config
        avail = registry.list_available()

        # Get output directory
        output_dir = context.config.get("generate_output")
        if output_dir:
            output_dir = Path(output_dir)
        elif context.repo_path:
            output_dir = context.repo_path / "fuzz_targets"
        else:
            output_dir = Path.cwd() / "fuzz_targets"

        # Get LLM if configured
        llm = None
        use_llm = context.config.get("use_llm", True)
        if use_llm:
            try:
                if cfg.llm_provider in avail.get("llm_providers", []):
                    llm = registry.get_llm(cfg.llm_provider, **config_manager.env)
                    log.info("Using LLM provider: %s", cfg.llm_provider)
            except Exception as e:
                log.warning("Failed to initialize LLM: %s", e)

        # Get max targets from config
        max_targets = context.config.get("max_targets")
        use_subdirs = context.config.get("generate_subdirs", True)

        # Priority order: API functions, usage_contexts, other functions (fuzz_target + rest)
        api_functions = [f for f in functions if getattr(f, "is_api", False)]
        fuzz_only = [f for f in functions if getattr(f, "is_fuzz_target_candidate", False) and not getattr(f, "is_api", False)]
        other_functions = [f for f in functions if f not in api_functions and f not in fuzz_only]
        usage_contexts = context.usage_contexts or []

        ordered_items: list[tuple] = []
        for f in api_functions:
            ordered_items.append((f, "api"))
        for uc in usage_contexts:
            ordered_items.append((uc, "usage_contexts"))
        for f in fuzz_only + other_functions:
            ordered_items.append((f, "other"))

        if max_targets is not None:
            ordered_items = ordered_items[:max_targets]

        # Create generator
        generator = HarnessGenerator(
            llm=llm,
            language=context.language or cfg.language,
            output_dir=output_dir,
        )

        # Generate harnesses (with category for subdirs)
        log.info(
            "Generating harnesses: %d API, %d usage_contexts, %d other (total %d)%s",
            len(api_functions),
            len(usage_contexts),
            len(fuzz_only) + len(other_functions),
            len(ordered_items),
            f" (max {max_targets})" if max_targets else "",
        )
        harnesses = generator.generate_batch(
            functions=functions,
            usage_contexts=usage_contexts,
            use_llm=llm is not None,
            max_targets=None,
            ordered_items=ordered_items,
            use_subdirs=use_subdirs,
        )

        # Validate harnesses
        validate = context.config.get("validate", True)
        if validate:
            validator = SyntaxValidator(language=context.language or cfg.language)
            # Use quick validation (structural) unless full validation requested
            full_validate = context.config.get("full_validate", False)
            if full_validate:
                harnesses = validator.validate_batch(harnesses)
            else:
                harnesses = [validator.quick_validate(h) for h in harnesses]

        valid_count = sum(1 for h in harnesses if h.is_valid)
        log.info("Generated %d harnesses (%d valid)", len(harnesses), valid_count)

        # Write harnesses to files (optionally in api/, usage_contexts/, other/)
        written_paths: list[Path] = []
        if context.config.get("write_harnesses", True):
            try:
                written_paths = generator.write_harnesses(
                    harnesses, output_dir, use_subdirs=use_subdirs
                )
                log.info("Wrote %d harness files to %s", len(written_paths), output_dir)
            except Exception as e:
                log.warning("Failed to write harnesses: %s", e)

        # Update context
        context.fuzz_targets_dir = output_dir

        data: dict = {
            "generated_harnesses": harnesses,
            "fuzz_targets_dir": output_dir,
            "valid_count": valid_count,
            "written_paths": [str(p) for p in written_paths],
        }

        return StageResult(
            stage_name=self.name,
            success=True,
            message=f"Generated {len(harnesses)} harnesses ({valid_count} valid)",
            data=data,
        )

    def can_skip(self, context: PipelineContext) -> bool:
        """Can skip if harnesses already generated and output dir exists."""
        if context.generated_harnesses:
            return True
        if context.fuzz_targets_dir and context.fuzz_targets_dir.is_dir():
            # Check if there are any harness files
            cpp_files = list(context.fuzz_targets_dir.glob("harness_*.cpp"))
            return len(cpp_files) > 0
        return False
