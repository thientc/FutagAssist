"""CLI entry point for FutagAssist."""

from __future__ import annotations

from pathlib import Path

import click

from futagassist import __version__
from futagassist.core.config import ConfigManager
from futagassist.core.health import HealthChecker, HealthCheckResult
from futagassist.core.plugin_loader import PluginLoader
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import PipelineContext
from futagassist.stages import register_builtin_stages


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
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output.")
@click.option("--skip-llm", is_flag=True, help="Skip LLM connectivity check.")
@click.option("--skip-fuzzer", is_flag=True, help="Skip fuzzer engine check.")
def check(verbose: bool, skip_llm: bool, skip_fuzzer: bool) -> None:
    """Verify CodeQL, LLM, and fuzzer setup."""
    config, registry = _load_env_and_plugins()
    checker = HealthChecker(config=config, registry=registry)
    results = checker.check_all(skip_llm=skip_llm, skip_fuzzer=skip_fuzzer)
    all_ok = all(r.ok for r in results)
    for r in results:
        status = "OK" if r.ok else "FAIL"
        click.echo(f"  {r.name}: {status}")
        if verbose or not r.ok:
            click.echo(f"    {r.message}")
    if all_ok:
        click.echo("All checks passed.")
    else:
        click.echo("Some checks failed.", err=True)
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
@click.option("--install-prefix", "build_install_prefix", type=click.Path(path_type=Path), help="Install library to this directory for linking stage (adds --prefix and make/ninja install). Default: <repo>/install.")
@click.option("--build-script", "build_script", type=click.Path(path_type=Path), help="Use this script as the build command with CodeQL (run from repo root; overrides auto-extracted build). Path relative to --repo if not absolute; script should be executable.")
def build(
    repo_path: Path,
    db_path: Path | None,
    language: str,
    overwrite: bool,
    build_log_file: Path | None,
    build_verbose: bool,
    build_install_prefix: Path | None,
    build_script: Path | None,
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
            "build_install_prefix": build_install_prefix.resolve() if build_install_prefix else None,
            "build_script": str(build_script) if build_script else None,
        },
    )
    stage = registry.get_stage("build")
    result = stage.execute(ctx)
    if result.success and result.data.get("db_path"):
        click.echo(f"CodeQL database: {result.data['db_path']}")
        if result.data.get("install_prefix"):
            click.echo(f"Install prefix (for linking): {result.data['install_prefix']}")
        if result.data.get("build_log_file"):
            click.echo(f"Build log: {result.data['build_log_file']}")
    else:
        click.echo("Build failed.", err=True)
        if result.message:
            click.echo(result.message, err=True)
        if result.data and result.data.get("build_log_file"):
            click.echo(f"Build log: {result.data['build_log_file']}", err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
