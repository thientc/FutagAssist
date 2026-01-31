"""Tests for ReadmeAnalyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from futagassist.build.readme_analyzer import ReadmeAnalyzer


def test_readme_analyzer_heuristic_make(tmp_path: Path) -> None:
    """Without LLM, heuristic returns make when no README."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    (tmp_path / "foo").mkdir()
    cmds = analyzer.extract_build_commands(tmp_path)
    assert len(cmds) >= 1
    assert "make" in cmds[0].lower() or "make" in " ".join(cmds).lower()


def test_readme_analyzer_heuristic_cmake(tmp_path: Path) -> None:
    """Heuristic returns cmake sequence when README mentions cmake."""
    (tmp_path / "README.md").write_text("Build with cmake. Run: mkdir build && cd build && cmake .. && make")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    cmds = analyzer.extract_build_commands(tmp_path)
    assert any("cmake" in c.lower() for c in cmds) or any("make" in c.lower() for c in cmds)


def test_readme_analyzer_heuristic_configure(tmp_path: Path) -> None:
    """Heuristic returns configure && make when README mentions configure."""
    (tmp_path / "README").write_text("Run ./configure then make.")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    cmds = analyzer.extract_build_commands(tmp_path)
    assert len(cmds) >= 1
    assert "configure" in " ".join(cmds).lower() or "make" in " ".join(cmds).lower()


def test_readme_analyzer_with_llm(tmp_path: Path) -> None:
    """With mock LLM, extracted command is used."""
    class MockLLM:
        name = "mock"
        def complete(self, prompt: str, **kwargs): return "mkdir build && cd build && cmake .. && make"
        def check_health(self): return True

    (tmp_path / "README.md").write_text("Some doc")
    analyzer = ReadmeAnalyzer(llm_provider=MockLLM())
    cmds = analyzer.extract_build_commands(tmp_path)
    assert len(cmds) >= 1
    assert "cmake" in " ".join(cmds).lower()


def test_readme_analyzer_nonexistent_dir() -> None:
    """Non-directory path returns default make."""
    analyzer = ReadmeAnalyzer(llm_provider=None)
    cmds = analyzer.extract_build_commands(Path("/nonexistent/repo"))
    assert cmds == ["make"]


def test_readme_analyzer_file_based_autogen(tmp_path: Path) -> None:
    """Repos with configure.ac + autogen.sh but no configure get autogen.sh && configure && make."""
    (tmp_path / "configure.ac").write_text("AC_INIT")
    (tmp_path / "Makefile.am").write_text("SUBDIRS = .")
    (tmp_path / "autogen.sh").write_text("#!/bin/sh\nautoreconf -fi")
    # No configure script (git clone style)
    analyzer = ReadmeAnalyzer(llm_provider=None)
    cmds = analyzer.extract_build_commands(tmp_path)
    assert len(cmds) >= 1
    full = " && ".join(cmds)
    assert "autogen" in full
    assert "configure" in full
    assert "make" in full


def test_readme_analyzer_file_based_configure_exists(tmp_path: Path) -> None:
    """Repos with existing configure script (no autogen.sh) get configure && make."""
    (tmp_path / "configure").write_text("#!/bin/sh\nexit 0")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    cmds = analyzer.extract_build_commands(tmp_path)
    full = " && ".join(cmds)
    assert "./configure" in full or "configure" in full
    assert "make" in full


def test_readme_analyzer_file_based_configure_preferred_when_both_exist(tmp_path: Path) -> None:
    """Repos with both configure and autogen.sh (e.g. libpng) use configure only; autogen.sh can refuse 'partial' trees."""
    (tmp_path / "configure.ac").write_text("AC_INIT")
    (tmp_path / "autogen.sh").write_text("#!/bin/sh\nautoreconf -fi")
    (tmp_path / "configure").write_text("#!/bin/sh\nexit 0")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    cmds = analyzer.extract_build_commands(tmp_path)
    full = " && ".join(cmds)
    assert "autogen" not in full
    assert "./configure" in full or "configure" in full
    assert "make" in full


def test_readme_analyzer_file_based_meson(tmp_path: Path) -> None:
    """Repos with meson.build get meson setup build && ninja -C build."""
    (tmp_path / "meson.build").write_text("project('foo', 'c')")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    cmds = analyzer.extract_build_commands(tmp_path)
    full = " && ".join(cmds)
    assert "meson" in full
    assert "ninja" in full
    assert "build" in full


def test_readme_analyzer_install_prefix_autotools(tmp_path: Path) -> None:
    """With install_prefix, autotools get --prefix and make install."""
    (tmp_path / "configure").write_text("#!/bin/sh\nexit 0")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    prefix = tmp_path / "install"
    cmds = analyzer.extract_build_commands(tmp_path, install_prefix=prefix)
    full = " && ".join(cmds)
    assert "--prefix=" in full
    assert "install" in str(prefix) or "install" in full
    assert "make install" in full


def test_readme_analyzer_install_prefix_meson(tmp_path: Path) -> None:
    """With install_prefix, Meson get --prefix and ninja install."""
    (tmp_path / "meson.build").write_text("project('foo', 'c')")
    analyzer = ReadmeAnalyzer(llm_provider=None)
    prefix = tmp_path / "install"
    cmds = analyzer.extract_build_commands(tmp_path, install_prefix=prefix)
    full = " && ".join(cmds)
    assert "meson" in full and "ninja" in full
    assert "install" in full
    assert "--prefix=" in full
