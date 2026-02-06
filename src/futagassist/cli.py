"""CLI entry point for FutagAssist."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from futagassist import __version__
from futagassist.core.config import ConfigManager
from futagassist.core.health import HealthChecker, HealthCheckResult
from futagassist.core.plugin_loader import PluginLoader
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import FunctionInfo, PipelineContext, UsageContext
from futagassist.reporters import register_builtin_reporters
from futagassist.stages import register_builtin_stages


def _is_build_interactive(no_interactive: bool) -> bool:
    """True if build command should prompt (e.g. for suggested fix). Used so tests can override."""
    return sys.stdin.isatty() and not no_interactive


def _load_env_and_plugins(project_root: Path | None = None) -> tuple[ConfigManager, ComponentRegistry]:
    """Load .env and discover/load plugins; return config and registry."""
    try:
        from dotenv import load_dotenv
        root = project_root or Path.cwd()
        load_dotenv(root / ".env")
    except Exception:
        pass
    config = ConfigManager(project_root=project_root)
    config.load()
    registry = ComponentRegistry()
    register_builtin_stages(registry)
    register_builtin_reporters(registry)
    root = project_root or config.project_root
    if (plugins_path := root / "plugins").exists():
        loader = PluginLoader([plugins_path], registry)
        loader.load_all()
    return config, registry


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """FutagAssist: Intelligent fuzzing assistant using CodeQL and LLMs."""
    pass


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output (paths, suggestions).")
@click.option("--skip-llm", is_flag=True, help="Skip LLM connectivity check.")
@click.option("--skip-fuzzer", is_flag=True, help="Skip fuzzer engine check.")
@click.option("--skip-plugins", is_flag=True, help="Skip plugins / language analyzer check.")
def check(verbose: bool, skip_llm: bool, skip_fuzzer: bool, skip_plugins: bool) -> None:
    """Verify CodeQL, LLM, plugins, and fuzzer setup; show suggestions for failures."""
    config, registry = _load_env_and_plugins()
    checker = HealthChecker(config=config, registry=registry)
    results = checker.check_all(
        skip_llm=skip_llm,
        skip_fuzzer=skip_fuzzer,
        skip_plugins=skip_plugins,
        verify_codeql_packs=verbose,
    )
    all_ok = all(r.ok for r in results)
    for r in results:
        status = "OK" if r.ok else "FAIL"
        click.echo(f"  {r.name}: {status}")
        if verbose or not r.ok:
            click.echo(f"    {r.message}")
        if (verbose or not r.ok) and r.suggestion:
            click.echo(f"    → {r.suggestion}")
    if all_ok:
        # Show any non-fatal hints (e.g. CodeQL packs suggestion when version OK but packs missing)
        hints = [r.suggestion for r in results if r.suggestion and r.ok]
        if hints:
            click.echo("All checks passed. Hints:")
            for h in hints:
                click.echo(f"  → {h}")
        else:
            click.echo("All checks passed.")
    else:
        click.echo("Some checks failed. Fix the issues above or follow the suggested steps.", err=True)
        raise SystemExit(1)


@main.group()
def plugins() -> None:
    """List or manage plugins."""
    pass


@plugins.command("list")
def plugins_list() -> None:
    """List available plugins (LLM providers, fuzzers, languages, reporters)."""
    _, registry = _load_env_and_plugins()
    avail = registry.list_available()
    click.echo("Available components:")
    for kind, names in avail.items():
        label = kind.replace("_", " ").title()
        click.echo(f"  {label}: {', '.join(names) or '(none)'}")


@main.command()
@click.option("--repo", "repo_path", required=True, type=click.Path(path_type=Path, exists=True), help="Repository or project path.")
@click.option("--output", "db_path", type=click.Path(path_type=Path), help="Output CodeQL database path (default: <repo>/codeql-db).")
@click.option("--language", default="cpp", help="Language for CodeQL database (default: cpp).")
@click.option("--overwrite", is_flag=True, help="Overwrite existing CodeQL database directory if it exists.")
@click.option("--log-file", "build_log_file", type=click.Path(path_type=Path), help="Write build-stage log to this file (default: <repo>/futagassist-build.log).")
@click.option("--verbose", "-v", "build_verbose", is_flag=True, help="Verbose build log (DEBUG level, includes full LLM prompts/responses).")
@click.option("--build-script", "build_script", type=click.Path(path_type=Path), help="Use this script as the build command with CodeQL (run from repo root; overrides auto-extracted build). Path relative to --repo if not absolute; script should be executable.")
@click.option("--configure-options", "build_configure_options", default=None, help="Extra flags for the configure step (e.g. --without-ssl). Ignored when using --build-script.")
@click.option("--no-interactive", "no_interactive", is_flag=True, help="Never prompt (e.g. in CI); on failure with a suggested fix, print and exit without asking to run it.")
def build(
    repo_path: Path,
    db_path: Path | None,
    language: str,
    overwrite: bool,
    build_log_file: Path | None,
    build_verbose: bool,
    build_script: Path | None,
    build_configure_options: str | None,
    no_interactive: bool,
) -> None:
    """Build project and create CodeQL database (README analysis + CodeQL wrapper)."""
    config, registry = _load_env_and_plugins()
    ctx = PipelineContext(
        repo_path=repo_path.resolve(),
        db_path=db_path.resolve() if db_path else None,
        language=language,
        config={
            "registry": registry,
            "config_manager": config,
            "build_overwrite": overwrite,
            "build_log_file": build_log_file.resolve() if build_log_file else None,
            "build_verbose": build_verbose,
            "build_script": str(build_script) if build_script else None,
            "build_configure_options": build_configure_options,
        },
    )
    stage = registry.get_stage("build")
    result = stage.execute(ctx)
    if result.success and result.data.get("db_path"):
        click.echo("Build succeeded.")
        click.echo(f"CodeQL database: {result.data['db_path']}")
        if result.data.get("build_log_file"):
            click.echo(f"Build log: {result.data['build_log_file']}")
        return

    # Build failed
    click.echo("Build failed.", err=True)
    if result.message:
        click.echo(result.message, err=True)
    if result.data and result.data.get("build_log_file"):
        click.echo(f"Build log: {result.data['build_log_file']}", err=True)

    suggested_fix = result.data.get("suggested_fix_command") if result.data else None
    interactive = _is_build_interactive(no_interactive)

    # Interactive: offer to add configure options for retry (e.g. --without-ssl for curl)
    if interactive:
        configure_opts_input = click.prompt(
            "Add configure options for retry? (e.g. --without-ssl) [leave empty to skip]",
            default="",
            show_default=False,
            err=True,
        )
        if configure_opts_input and configure_opts_input.strip():
            ctx.config["build_configure_options"] = configure_opts_input.strip()
            result = stage.execute(ctx)
            if result.success and result.data.get("db_path"):
                click.echo("Build succeeded.")
                click.echo(f"CodeQL database: {result.data['db_path']}")
                if result.data.get("build_log_file"):
                    click.echo(f"Build log: {result.data['build_log_file']}")
                return
            click.echo("Build failed after retry.", err=True)
            if result.message:
                click.echo(result.message, err=True)
            if result.data and result.data.get("build_log_file"):
                click.echo(f"Build log: {result.data['build_log_file']}", err=True)
            raise SystemExit(1)

    # Interactive: offer to run LLM-suggested fix
    if suggested_fix and interactive:
        if "sudo" in suggested_fix:
            click.echo("Warning: suggested command contains 'sudo'.", err=True)
        if click.confirm("Run this fix and retry build?", default=False):
            try:
                run = subprocess.run(
                    suggested_fix,
                    shell=True,
                    cwd=str(repo_path.resolve()),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if run.returncode != 0 and run.stderr:
                    click.echo(run.stderr, err=True)
            except subprocess.TimeoutExpired:
                click.echo("Fix command timed out (120s).", err=True)
            except Exception as e:
                click.echo(f"Fix command failed: {e}", err=True)
            # Retry build once (whether fix succeeded or not)
            result = stage.execute(ctx)
            if result.success and result.data.get("db_path"):
                click.echo("Build succeeded.")
                click.echo(f"CodeQL database: {result.data['db_path']}")
                if result.data.get("build_log_file"):
                    click.echo(f"Build log: {result.data['build_log_file']}")
                return
            click.echo("Build failed after retry.", err=True)
            if result.message:
                click.echo(result.message, err=True)
            if result.data and result.data.get("build_log_file"):
                click.echo(f"Build log: {result.data['build_log_file']}", err=True)

    raise SystemExit(1)


@main.command("fuzz-build")
@click.option("--repo", "repo_path", required=True, type=click.Path(path_type=Path, exists=True), help="Repository or project path.")
@click.option("--prefix", "fuzz_install_prefix", type=click.Path(path_type=Path), help="Install prefix for instrumented build (default: <repo>/install-fuzz).")
@click.option("--configure-options", "fuzz_build_configure_options", default=None, help="Extra flags for the configure step (e.g. --without-ssl).")
@click.option("--log-file", "fuzz_build_log_file", type=click.Path(path_type=Path), help="Write fuzz-build log to this file (default: <repo>/futagassist-fuzz-build.log).")
@click.option("--verbose", "-v", "fuzz_build_verbose", is_flag=True, help="Verbose fuzz-build log.")
def fuzz_build(
    repo_path: Path,
    fuzz_install_prefix: Path | None,
    fuzz_build_configure_options: str | None,
    fuzz_build_log_file: Path | None,
    fuzz_build_verbose: bool,
) -> None:
    """Build library with debug + sanitizers (ASan/UBSan) and install to fuzz prefix."""
    config, registry = _load_env_and_plugins()
    ctx = PipelineContext(
        repo_path=repo_path.resolve(),
        config={
            "registry": registry,
            "config_manager": config,
            "fuzz_install_prefix": str(fuzz_install_prefix.resolve()) if fuzz_install_prefix else None,
            "fuzz_build_log_file": fuzz_build_log_file.resolve() if fuzz_build_log_file else None,
            "fuzz_build_verbose": fuzz_build_verbose,
            "fuzz_build_configure_options": fuzz_build_configure_options,
        },
    )
    stage = registry.get_stage("fuzz_build")
    result = stage.execute(ctx)
    if result.success:
        click.echo("Fuzz build succeeded.")
        if result.data.get("fuzz_install_prefix"):
            click.echo(f"Instrumented install: {result.data['fuzz_install_prefix']}")
        if result.data.get("fuzz_build_log_file"):
            click.echo(f"Log: {result.data['fuzz_build_log_file']}")
        return
    click.echo("Fuzz build failed.", err=True)
    if result.message:
        click.echo(result.message, err=True)
    if result.data and result.data.get("fuzz_build_log_file"):
        click.echo(f"Log: {result.data['fuzz_build_log_file']}", err=True)
    raise SystemExit(1)


@main.command()
@click.option("--db", "db_path", required=True, type=click.Path(path_type=Path, exists=True), help="Path to CodeQL database (from build stage).")
@click.option("--output", "output_path", type=click.Path(path_type=Path), help="Write function list to this JSON file.")
@click.option("--language", default="cpp", help="Language for analysis (default: cpp).")
def analyze(db_path: Path, output_path: Path | None, language: str) -> None:
    """Extract function info from CodeQL database (delegates to LanguageAnalyzer)."""
    config, registry = _load_env_and_plugins()
    ctx = PipelineContext(
        repo_path=None,
        db_path=db_path.resolve(),
        language=language,
        config={
            "registry": registry,
            "config_manager": config,
            "analyze_output": str(output_path.resolve()) if output_path else None,
        },
    )
    stage = registry.get_stage("analyze")
    result = stage.execute(ctx)
    if not result.success:
        click.echo(result.message or "Analysis failed.", err=True)
        raise SystemExit(1)
    n = len(result.data.get("functions", []))
    click.echo(f"Analyzed {n} function(s).")
    if result.data.get("analyze_output"):
        click.echo(f"Wrote {result.data['analyze_output']}")


@main.command()
@click.option(
    "--functions",
    "functions_path",
    required=True,
    type=click.Path(path_type=Path, exists=True),
    help="Path to functions JSON file from analyze stage (contains 'functions' and optionally 'usage_contexts').",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    help="Output directory for generated harnesses (default: ./fuzz_targets).",
)
@click.option("--max-targets", type=int, default=None, help="Maximum number of harnesses to generate.")
@click.option("--no-llm", is_flag=True, help="Disable LLM-based generation (template-only).")
@click.option("--no-validate", is_flag=True, help="Skip syntax validation.")
@click.option("--full-validate", is_flag=True, help="Use clang++ -fsyntax-only (slower, more accurate).")
@click.option("--language", default="cpp", help="Language for harness generation (default: cpp).")
@click.option(
    "--no-subdirs",
    is_flag=True,
    help="Do not write category subdirectories (api/, usage_contexts/, other/).",
)
def generate(
    functions_path: Path,
    output_dir: Path | None,
    max_targets: int | None,
    no_llm: bool,
    no_validate: bool,
    full_validate: bool,
    language: str,
    no_subdirs: bool,
) -> None:
    """Generate fuzz harnesses from analyze-stage JSON."""
    config, registry = _load_env_and_plugins()

    try:
        payload = json.loads(functions_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        click.echo(f"Failed to read/parse functions JSON: {e}", err=True)
        raise SystemExit(1)

    functions_raw = payload.get("functions") if isinstance(payload, dict) else payload
    contexts_raw = payload.get("usage_contexts", []) if isinstance(payload, dict) else []

    if not isinstance(functions_raw, list):
        click.echo("Invalid functions JSON: expected top-level list or object with 'functions' list.", err=True)
        raise SystemExit(1)

    try:
        functions = [FunctionInfo.model_validate(x) for x in functions_raw]
        usage_contexts = [UsageContext.model_validate(x) for x in contexts_raw] if isinstance(contexts_raw, list) else []
    except Exception as e:
        click.echo(f"Invalid functions JSON schema: {e}", err=True)
        raise SystemExit(1)

    ctx = PipelineContext(
        repo_path=None,
        db_path=None,
        language=language,
        functions=functions,
        usage_contexts=usage_contexts,
        config={
            "registry": registry,
            "config_manager": config,
            "generate_output": str(output_dir.resolve()) if output_dir else None,
            "use_llm": not no_llm,
            "validate": not no_validate,
            "full_validate": full_validate,
            "max_targets": max_targets,
            "generate_subdirs": not no_subdirs,
            "write_harnesses": True,
        },
    )

    stage = registry.get_stage("generate")
    result = stage.execute(ctx)
    if not result.success:
        click.echo(result.message or "Generate failed.", err=True)
        raise SystemExit(1)

    click.echo(result.message or "Generate succeeded.")
    if result.data.get("fuzz_targets_dir"):
        click.echo(f"Output dir: {result.data['fuzz_targets_dir']}")
    if result.data.get("valid_count") is not None:
        click.echo(f"Valid harnesses: {result.data['valid_count']}")


@main.command()
@click.option(
    "--targets",
    "targets_dir",
    required=True,
    type=click.Path(path_type=Path, exists=True),
    help="Directory containing generated harness sources (from generate stage).",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    help="Output directory for compiled binaries (default: ./fuzz_binaries).",
)
@click.option("--prefix", "fuzz_install_prefix", type=click.Path(path_type=Path), help="Instrumented library install prefix (from fuzz-build stage).")
@click.option("--compiler", default="clang++", help="Compiler to use (default: clang++).")
@click.option("--retry", "max_retries", type=int, default=3, help="Max LLM-assisted retries per harness (default: 3).")
@click.option("--no-llm", is_flag=True, help="Disable LLM-assisted error fixing.")
@click.option("--language", default="cpp", help="Language for compiler flags (default: cpp).")
@click.option("--timeout", "compile_timeout", type=int, default=120, help="Compiler timeout in seconds (default: 120).")
def compile(
    targets_dir: Path,
    output_dir: Path | None,
    fuzz_install_prefix: Path | None,
    compiler: str,
    max_retries: int,
    no_llm: bool,
    language: str,
    compile_timeout: int,
) -> None:
    """Compile fuzz harnesses into instrumented binaries."""
    config, registry = _load_env_and_plugins()

    # Discover harness source files in target dir
    source_files = sorted(targets_dir.rglob("harness_*.cpp")) + sorted(targets_dir.rglob("fuzz_*.cpp"))
    if not source_files:
        # Fallback: any .cpp file
        source_files = sorted(targets_dir.rglob("*.cpp"))
    if not source_files:
        click.echo("No harness source files found in target directory.", err=True)
        raise SystemExit(1)

    # Build GeneratedHarness objects from source files
    from futagassist.core.schema import GeneratedHarness
    harnesses = []
    for sf in source_files:
        code = sf.read_text(encoding="utf-8", errors="replace")
        name = sf.stem.removeprefix("harness_").removeprefix("fuzz_")
        harnesses.append(GeneratedHarness(
            function_name=name,
            file_path=str(sf),
            source_code=code,
            is_valid=True,
        ))

    ctx = PipelineContext(
        repo_path=targets_dir.parent,
        language=language,
        generated_harnesses=harnesses,
        fuzz_install_prefix=fuzz_install_prefix.resolve() if fuzz_install_prefix else None,
        config={
            "registry": registry,
            "config_manager": config,
            "compile_output": str(output_dir.resolve()) if output_dir else None,
            "compile_compiler": compiler,
            "compile_max_retries": max_retries,
            "compile_use_llm": not no_llm,
            "compile_timeout": compile_timeout,
        },
    )

    stage = registry.get_stage("compile")
    result = stage.execute(ctx)
    if not result.success:
        click.echo(result.message or "Compilation failed.", err=True)
        raise SystemExit(1)

    click.echo(result.message or "Compilation succeeded.")
    if result.data.get("binaries_dir"):
        click.echo(f"Binaries: {result.data['binaries_dir']}")
    if result.data.get("compiled_count") is not None:
        click.echo(f"Compiled: {result.data['compiled_count']}")
    if result.data.get("failed_count"):
        click.echo(f"Failed: {result.data['failed_count']}")


@main.command()
@click.option(
    "--binaries",
    "binaries_dir",
    required=True,
    type=click.Path(path_type=Path, exists=True),
    help="Directory containing compiled fuzz binaries (from compile stage).",
)
@click.option(
    "--output",
    "results_dir",
    type=click.Path(path_type=Path),
    help="Output directory for fuzz results (default: ./fuzz_results).",
)
@click.option("--engine", "fuzz_engine", default=None, help="Fuzzer engine to use (default: from config).")
@click.option("--max-time", "max_total_time", type=int, default=60, help="Max total fuzzing time per binary in seconds (default: 60).")
@click.option("--timeout", "fuzz_timeout", type=int, default=30, help="Timeout per test case in seconds (default: 30).")
@click.option("--fork", type=int, default=1, help="Number of fork workers (default: 1).")
@click.option("--rss-limit", "rss_limit_mb", type=int, default=2048, help="RSS memory limit in MB (default: 2048).")
@click.option("--no-coverage", is_flag=True, help="Skip coverage collection.")
def fuzz(
    binaries_dir: Path,
    results_dir: Path | None,
    fuzz_engine: str | None,
    max_total_time: int,
    fuzz_timeout: int,
    fork: int,
    rss_limit_mb: int,
    no_coverage: bool,
) -> None:
    """Run compiled fuzz targets through a fuzzer engine."""
    config, registry = _load_env_and_plugins()

    # Discover binaries
    binaries_list = sorted(
        f for f in binaries_dir.iterdir()
        if f.is_file() and not f.suffix
    )
    if not binaries_list:
        click.echo("No fuzz binaries found in directory.", err=True)
        raise SystemExit(1)

    ctx = PipelineContext(
        repo_path=binaries_dir.parent,
        binaries_dir=binaries_dir.resolve(),
        config={
            "registry": registry,
            "config_manager": config,
            "fuzz_engine": fuzz_engine,
            "fuzz_results_dir": str(results_dir.resolve()) if results_dir else None,
            "fuzz_max_total_time": max_total_time,
            "fuzz_timeout": fuzz_timeout,
            "fuzz_fork": fork,
            "fuzz_rss_limit_mb": rss_limit_mb,
            "fuzz_coverage": not no_coverage,
        },
    )

    stage = registry.get_stage("fuzz")
    result = stage.execute(ctx)
    if not result.success:
        click.echo(result.message or "Fuzzing failed.", err=True)
        raise SystemExit(1)

    click.echo(result.message or "Fuzzing complete.")
    if result.data.get("results_dir"):
        click.echo(f"Results: {result.data['results_dir']}")
    if result.data.get("unique_crashes"):
        click.echo(f"Unique crashes: {result.data['unique_crashes']}")


@main.command()
@click.option(
    "--results",
    "results_dir",
    type=click.Path(path_type=Path, exists=True),
    help="Directory containing fuzz results (from fuzz stage).",
)
@click.option(
    "--output",
    "report_output",
    type=click.Path(path_type=Path),
    help="Output directory for reports (default: ./reports).",
)
@click.option(
    "--format",
    "report_formats",
    multiple=True,
    help="Report format(s) to generate (e.g. json, sarif, html). Repeatable. Default: all registered.",
)
@click.option(
    "--functions",
    "functions_path",
    type=click.Path(path_type=Path, exists=True),
    help="Path to functions JSON file (from analyze stage) to include in reports.",
)
def report(
    results_dir: Path | None,
    report_output: Path | None,
    report_formats: tuple[str, ...],
    functions_path: Path | None,
) -> None:
    """Generate reports from fuzzing results."""
    config, registry = _load_env_and_plugins()

    functions: list[FunctionInfo] = []
    if functions_path:
        try:
            payload = json.loads(functions_path.read_text(encoding="utf-8", errors="replace"))
            raw = payload.get("functions") if isinstance(payload, dict) else payload
            if isinstance(raw, list):
                functions = [FunctionInfo.model_validate(x) for x in raw]
        except Exception as e:
            click.echo(f"Warning: could not load functions JSON: {e}", err=True)

    ctx = PipelineContext(
        repo_path=Path.cwd(),
        results_dir=results_dir.resolve() if results_dir else None,
        functions=functions,
        config={
            "registry": registry,
            "config_manager": config,
            "report_output": str(report_output.resolve()) if report_output else None,
            "report_formats": list(report_formats) if report_formats else None,
        },
    )

    stage = registry.get_stage("report")
    result = stage.execute(ctx)
    if not result.success:
        click.echo(result.message or "Report generation failed.", err=True)
        raise SystemExit(1)

    click.echo(result.message or "Reports generated.")
    if result.data.get("report_output"):
        click.echo(f"Output: {result.data['report_output']}")
    if result.data.get("written_files"):
        for f in result.data["written_files"]:
            click.echo(f"  {f}")


if __name__ == "__main__":
    main()
