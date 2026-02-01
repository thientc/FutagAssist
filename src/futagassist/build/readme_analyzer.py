"""Extract build steps from README/INSTALL using LLM or heuristics."""

from __future__ import annotations

import re
from pathlib import Path

from futagassist.build.build_log import get_logger

BUILD_EXTRACT_PROMPT = """You are analyzing a software project's documentation to extract the exact build/compile steps.

Given the following documentation content, output ONLY a single shell command (or commands joined by " && ") that would build this project from the repository root. Assume we are already in the project root directory. Do not include "cd" into the project. Output nothing else except the command(s).

Documentation:
---
{docs}
---

Single build command (or "cmd1 && cmd2"):"""


class ReadmeAnalyzer:
    """Extract build commands from README, INSTALL, or similar files using LLM or heuristics."""

    def __init__(self, llm_provider=None):
        """Optional llm_provider (LLMProvider protocol) for LLM-based extraction."""
        self._llm = llm_provider

    def _gather_docs(self, repo_path: Path) -> str:
        """Gather content from README, INSTALL, etc."""
        log = get_logger()
        candidates = [
            "README.md",
            "README",
            "INSTALL.md",
            "INSTALL",
            "BUILD.md",
            "BUILD",
            "README.rst",
            "CONTRIBUTING.md",
        ]
        parts: list[str] = []
        found: list[str] = []
        for name in candidates:
            p = repo_path / name
            if p.exists() and p.is_file():
                try:
                    text = p.read_text(errors="ignore")
                    if text.strip():
                        parts.append(f"--- {name} ---\n{text[:8000]}")
                        found.append(name)
                except Exception:
                    pass
        result = "\n\n".join(parts) if parts else "No README or INSTALL found."
        log.info("README analysis: gathered docs from %s", found if found else ["(none)"])
        return result

    def _extract_via_llm(self, docs: str) -> str:
        """Use LLM to extract build command from docs."""
        log = get_logger()
        if not self._llm:
            return ""
        prompt = BUILD_EXTRACT_PROMPT.format(docs=docs)
        log.info("README analysis: using LLM to extract build command")
        log.debug("LLM prompt (build extraction):\n%s", prompt[:2000] + ("..." if len(prompt) > 2000 else ""))
        try:
            out = self._llm.complete(prompt).strip()
            log.debug("LLM response (build extraction):\n%s", out[:1500] + ("..." if len(out) > 1500 else ""))
            # Take first line and remove markdown code fence
            line = out.split("\n")[0].strip()
            if line.startswith("```"):
                line = re.sub(r"^```\w*\n?", "", line).strip()
            if line.endswith("```"):
                line = line.rsplit("```", 1)[0].strip()
            cmd = line if line else ""
            if cmd:
                log.info("LLM extracted build command: %s", cmd)
            return cmd
        except Exception as e:
            log.warning("LLM build extraction failed: %s", e)
            return ""

    def _install_suffix(self, install_prefix: str | Path | None) -> str:
        """Return install prefix for shell (absolute path), or empty if not set."""
        if install_prefix is None:
            return ""
        return str(Path(install_prefix).resolve())

    def _detect_build_from_files(
        self, repo_path: Path, install_prefix: str | Path | None = None
    ) -> str:
        """
        Detect build system from repo files (configure, configure.ac, meson.build, CMakeLists.txt).
        If install_prefix is set, configure/cmake/meson use it and 'make install' (or ninja install) is appended
        for use by a future linking stage.
        """
        log = get_logger()
        repo_path = Path(repo_path).resolve()
        prefix = self._install_suffix(install_prefix)

        configure_script = repo_path / "configure"
        has_configure_ac = (repo_path / "configure.ac").is_file()
        has_makefile_am = (repo_path / "Makefile.am").is_file()
        autogen = repo_path / "autogen.sh"

        # Autotools: configure exists -> use it (some projects' autogen.sh refuses "partial" trees, e.g. libpng)
        if configure_script.exists() and configure_script.is_file():
            cmd = f"./configure --prefix={prefix}" if prefix else "./configure"
            cmd += " && make"
            if prefix:
                cmd += " && make install"
            log.info("README analysis: file-based (configure exists) -> %s", cmd)
            return cmd

        # Autotools from git: no configure but configure.ac/Makefile.am + autogen.sh -> run autogen.sh first
        if (has_configure_ac or has_makefile_am) and autogen.is_file():
            cfg = f"./configure --prefix={prefix}" if prefix else "./configure"
            cmd = f"./autogen.sh && {cfg} && make"
            if prefix:
                cmd += " && make install"
            log.info("README analysis: file-based (configure.ac + autogen.sh, no configure) -> %s", cmd)
            return cmd

        # Meson: meson.build at root -> meson setup build [--prefix] && ninja -C build [&& ninja install]
        if (repo_path / "meson.build").is_file():
            cmd = f"meson setup build --prefix={prefix}" if prefix else "meson setup build"
            cmd += " && ninja -C build"
            if prefix:
                cmd += " && ninja -C build install"
            log.info("README analysis: file-based (meson.build) -> %s", cmd)
            return cmd

        # CMake: CMakeLists.txt at root (prefer if no autotools)
        if (repo_path / "CMakeLists.txt").is_file() and not has_configure_ac and not configure_script.exists():
            cmake_prefix = f" -DCMAKE_INSTALL_PREFIX={prefix}" if prefix else ""
            cmd = f"mkdir -p build && cd build && cmake{cmake_prefix} .. && make"
            if prefix:
                cmd += " && make install"
            log.info("README analysis: file-based (CMakeLists.txt) -> %s", cmd)
            return cmd

        return ""

    def _extract_heuristic(
        self, docs: str, install_prefix: str | Path | None = None
    ) -> str:
        """Heuristic fallback: look for common build patterns. If install_prefix set, add --prefix and install."""
        log = get_logger()
        docs_lower = docs.lower()
        prefix = self._install_suffix(install_prefix)
        if "cmake" in docs_lower and ("mkdir build" in docs_lower or "build" in docs_lower):
            cmake_prefix = f" -DCMAKE_INSTALL_PREFIX={prefix}" if prefix else ""
            cmd = f"mkdir -p build && cd build && cmake{cmake_prefix} .. && make"
            if prefix:
                cmd += " && make install"
            log.info("README analysis: using heuristic -> %s", cmd)
            return cmd
        if "meson" in docs_lower:
            cmd = f"meson setup build --prefix={prefix}" if prefix else "meson setup build"
            cmd += " && ninja -C build"
            if prefix:
                cmd += " && ninja -C build install"
            log.info("README analysis: using heuristic -> %s", cmd)
            return cmd
        if "autoconf" in docs_lower or "configure" in docs_lower:
            cfg = f"./configure --prefix={prefix}" if prefix else "./configure"
            cmd = f"{cfg} && make"
            if prefix:
                cmd += " && make install"
            log.info("README analysis: using heuristic -> %s", cmd)
            return cmd
        if "makefile" in docs_lower or "make " in docs_lower:
            cmd = "make"
            if prefix:
                cmd += f" && make install PREFIX={prefix}"
            log.info("README analysis: using heuristic -> %s", cmd)
            return cmd
        cmd = "make"
        if prefix:
            cmd += f" && make install PREFIX={prefix}"
        log.info("README analysis: using heuristic -> %s (default)", cmd)
        return cmd

    def extract_build_commands(
        self,
        repo_path: Path,
        install_prefix: str | Path | None = None,
    ) -> list[str]:
        """
        Return a list of build command strings (each may be run in sequence).
        If install_prefix is set, build commands include --prefix and make/ninja install
        so the library is installed to that directory for a future linking stage.
        """
        log = get_logger()
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return ["make"]

        # 1) File-based detection (optionally with install prefix for linking stage)
        cmd = self._detect_build_from_files(repo_path, install_prefix=install_prefix)
        if not cmd:
            docs = self._gather_docs(repo_path)
            cmd = self._extract_via_llm(docs) if self._llm else ""
            if not cmd:
                cmd = self._extract_heuristic(docs, install_prefix=install_prefix)
        if not cmd:
            cmd = "make"
            if install_prefix:
                cmd += f" && make install PREFIX={self._install_suffix(install_prefix)}"

        # Split by " && " into sequential commands
        commands = [c.strip() for c in cmd.split(" && ") if c.strip()]
        log.info("Build commands (list): %s", commands)
        return commands

    def extract_clean_command(self, repo_path: Path) -> str:
        """
        Infer a clean command from the repo (for use with --overwrite).
        Returns a single shell command to run from repo root, or empty if unknown.
        """
        log = get_logger()
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return ""

        # Same file-based detection as build: autotools -> make clean, meson -> ninja -C build -t clean, cmake -> clean in build dir
        configure_script = repo_path / "configure"
        has_configure_ac = (repo_path / "configure.ac").is_file()
        has_makefile_am = (repo_path / "Makefile.am").is_file()
        autogen = repo_path / "autogen.sh"

        if configure_script.exists() and configure_script.is_file():
            log.info("Clean command (configure): make clean")
            return "make clean"
        if (has_configure_ac or has_makefile_am) and autogen.is_file():
            log.info("Clean command (autotools): make clean")
            return "make clean"
        if (repo_path / "meson.build").is_file():
            # ninja -C build -t clean removes built files; "ninja -C build clean" if clean target exists
            log.info("Clean command (meson): ninja -C build -t clean")
            return "ninja -C build -t clean"
        if (repo_path / "CMakeLists.txt").is_file() and not has_configure_ac and not configure_script.exists():
            log.info("Clean command (cmake): cmake --build build --target clean")
            return "cmake --build build --target clean"

        # Default: make clean (safe no-op if no Makefile)
        log.info("Clean command (default): make clean")
        return "make clean"
