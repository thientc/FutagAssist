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

        # Create generator
        generator = HarnessGenerator(
            llm=llm,
            language=context.language or cfg.language,
            output_dir=output_dir,
        )

        # Generate harnesses
        log.info(
            "Generating harnesses for %d functions%s",
            len(functions),
            f" (max {max_targets})" if max_targets else "",
        )
        harnesses = generator.generate_batch(
            functions=functions,
            usage_contexts=context.usage_contexts or None,
            use_llm=llm is not None,
            max_targets=max_targets,
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

        # Write harnesses to files
        written_paths: list[Path] = []
        if context.config.get("write_harnesses", True):
            try:
                written_paths = generator.write_harnesses(harnesses, output_dir)
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
