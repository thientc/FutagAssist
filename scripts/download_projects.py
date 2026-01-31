#!/usr/bin/env python3
"""
Download top critical C, C++, and Python projects (OSS-Fuzz style).

Reads config/libs_projects.yaml and clones each repo into libs/<name>.
Usage:
  python scripts/download_projects.py [--config CONFIG] [--output DIR] [--project NAME] [--list] [--shallow]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def find_project_root() -> Path:
    """Find repo root by looking for config/ or pyproject.toml upward."""
    current = Path.cwd().resolve()
    for _ in range(10):
        if (current / "config").is_dir() or (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.cwd().resolve()


def load_config(config_path: Path) -> list[dict]:
    """Load libs_projects.yaml and return list of project dicts."""
    try:
        import yaml
    except ImportError:
        print("error: pyyaml required. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    if not config_path.exists():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    projects = data.get("projects") or []
    if not isinstance(projects, list):
        print("error: config 'projects' must be a list", file=sys.stderr)
        sys.exit(1)
    return projects


def run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    """Run git command; return (success, stderr_or_stdout)."""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            return False, r.stderr or r.stdout or f"exit {r.returncode}"
        return True, r.stdout or ""
    except FileNotFoundError:
        return False, "git not found"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def clone_project(
    repo_url: str,
    dest: Path,
    branch: str | None = None,
    shallow: bool = False,
) -> tuple[bool, str]:
    """Clone repo into dest; optionally checkout branch. Returns (success, message)."""
    dest = Path(dest).resolve()
    if dest.exists():
        if (dest / ".git").exists():
            return True, f"already exists: {dest}"
        return False, f"path exists and is not a git repo: {dest}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["clone", repo_url, str(dest)]
    if shallow:
        args.insert(-1, "--depth")
        args.insert(-1, "1")
    if branch:
        args.extend(["--branch", branch])

    ok, msg = run_git(args)
    if not ok:
        return False, msg
    return True, f"cloned: {dest}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download top critical C/C++/Python projects (OSS-Fuzz style).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to libs_projects.yaml (default: <project_root>/config/libs_projects.yaml)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output directory for clones (default: <project_root>/libs)",
    )
    parser.add_argument(
        "--project",
        "-p",
        type=str,
        default=None,
        help="Download only this project by name",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List projects from config and exit",
    )
    parser.add_argument(
        "--shallow",
        action="store_true",
        help="Shallow clone (--depth 1)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    root = find_project_root()
    config_path = args.config or (root / "config" / "libs_projects.yaml")
    out_dir = args.output or (root / "libs")

    projects = load_config(config_path)
    if args.list:
        print(f"Projects in {config_path}:")
        for p in projects:
            name = p.get("name", "?")
            lang = p.get("language", "?")
            url = p.get("repo_url", "?")
            branch = p.get("branch", "")
            print(f"  {name:<20} {lang:<6} {url}  {f'[{branch}]' if branch else ''}")
        return 0

    if args.project:
        projects = [p for p in projects if p.get("name") == args.project]
        if not projects:
            print(f"error: project not found: {args.project}", file=sys.stderr)
            return 1

    failed = []
    for p in projects:
        name = p.get("name")
        repo_url = p.get("repo_url")
        branch = p.get("branch")
        if not name or not repo_url:
            print(f"skip: invalid entry (missing name or repo_url)", file=sys.stderr)
            failed.append(name or "?")
            continue
        dest = out_dir / name
        if args.verbose:
            print(f"clone {name} -> {dest} ...")
        ok, msg = clone_project(repo_url, dest, branch=branch, shallow=args.shallow)
        if ok:
            print(f"  {name}: {msg}")
        else:
            print(f"  {name}: FAILED - {msg}", file=sys.stderr)
            failed.append(name)

    if failed:
        print(f"\nFailed: {len(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
