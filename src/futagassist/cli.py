"""CLI entry point for FutagAssist."""

from __future__ import annotations

from pathlib import Path

import click

from futagassist import __version__
from futagassist.core.config import ConfigManager
from futagassist.core.health import HealthChecker, HealthCheckResult
from futagassist.core.plugin_loader import PluginLoader
from futagassist.core.registry import ComponentRegistry


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
    plugin_dirs = [root / "plugins"] if (root := (project_root or config.project_root)) else []
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


if __name__ == "__main__":
    main()
