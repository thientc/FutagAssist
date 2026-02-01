"""CLI entry point for FutagAssist."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from futagassist import __version__
from futagassist.core.config import ConfigManager
from futagassist.core.health import HealthChecker, HealthCheckResult
from futagassist.core.plugin_loader import PluginLoader
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import PipelineContext
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
@click.option("--no-interactive", "no_interactive", is_flag=True, help="Never prompt (e.g. in CI); on failure with a suggested fix, print and exit without asking to run it.")
def build(
    repo_path: Path,
    db_path: Path | None,
    language: str,
    overwrite: bool,
    build_log_file: Path | None,
    build_verbose: bool,
    build_script: Path | None,
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


if __name__ == "__main__":
    main()
