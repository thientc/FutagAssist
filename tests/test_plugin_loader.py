"""Tests for PluginLoader."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from futagassist.core.exceptions import PluginLoadError
from futagassist.core.plugin_loader import PluginLoader
from futagassist.core.registry import ComponentRegistry


def test_plugin_loader_discover_empty_dir(tmp_path: Path) -> None:
    reg = ComponentRegistry()
    loader = PluginLoader([tmp_path], reg)
    discovered = loader.discover_plugins()
    assert discovered == []


def test_plugin_loader_discover_finds_py_files(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x = 1\n")
    reg = ComponentRegistry()
    loader = PluginLoader([tmp_path], reg)
    discovered = loader.discover_plugins()
    assert len(discovered) == 1
    assert discovered[0].name == "foo"
    assert discovered[0].path == tmp_path / "foo.py"


def test_plugin_loader_load_plugin_registers(tmp_path: Path) -> None:
    plugin_file = tmp_path / "my_plugin.py"
    plugin_file.write_text('''
def register(registry):
    from tests.test_registry import _MockLLM
    registry.register_llm("from_plugin", _MockLLM)
''')
    reg = ComponentRegistry()
    loader = PluginLoader([tmp_path], reg)
    loader.load_plugin(plugin_file)
    assert "from_plugin" in reg.list_available()["llm_providers"]
    provider = reg.get_llm("from_plugin")
    assert provider.name == "mock_llm"


def test_plugin_loader_load_plugin_missing_register_raises(tmp_path: Path) -> None:
    plugin_file = tmp_path / "no_register.py"
    plugin_file.write_text("x = 1\n")
    reg = ComponentRegistry()
    loader = PluginLoader([tmp_path], reg)
    with pytest.raises(PluginLoadError, match="no register"):
        loader.load_plugin(plugin_file)


def test_plugin_loader_load_plugin_nonexistent_raises() -> None:
    reg = ComponentRegistry()
    loader = PluginLoader([], reg)
    with pytest.raises(PluginLoadError, match="does not exist"):
        loader.load_plugin(Path("/nonexistent/plugin.py"))


def test_plugin_loader_load_all(tmp_path: Path) -> None:
    sub = tmp_path / "llm"
    sub.mkdir()
    (sub / "openai_provider.py").write_text('''
def register(registry):
    from tests.test_registry import _MockLLM
    registry.register_llm("openai", _MockLLM)
''')
    reg = ComponentRegistry()
    loader = PluginLoader([tmp_path], reg)
    loaded = loader.load_all()
    assert len(loaded) >= 1
    assert "openai" in reg.list_available()["llm_providers"]


def test_plugin_loader_load_all_collects_errors(tmp_path: Path) -> None:
    """load_all() logs and collects errors instead of silently swallowing them."""
    # Create a plugin that raises during import
    (tmp_path / "bad_plugin.py").write_text("raise ImportError('deliberate')\n")
    # Create a good plugin
    (tmp_path / "good_plugin.py").write_text('''
def register(registry):
    from tests.test_registry import _MockLLM
    registry.register_llm("good", _MockLLM)
''')
    reg = ComponentRegistry()
    loader = PluginLoader([tmp_path], reg)
    loaded = loader.load_all()
    # Good plugin loaded despite the bad one
    assert "good" in reg.list_available()["llm_providers"]
    # Errors collected
    assert len(loader.load_errors) == 1
    path, err = loader.load_errors[0]
    assert "bad_plugin" in str(path)


def test_plugin_loader_skips_private_modules(tmp_path: Path) -> None:
    """Modules starting with _ are skipped during discovery."""
    (tmp_path / "_private.py").write_text("x = 1\n")
    (tmp_path / "public.py").write_text('''
def register(registry):
    from tests.test_registry import _MockLLM
    registry.register_llm("public", _MockLLM)
''')
    reg = ComponentRegistry()
    loader = PluginLoader([tmp_path], reg)
    discovered = loader.discover_plugins()
    names = [d.name for d in discovered]
    assert "_private" not in names
    assert "public" in names
