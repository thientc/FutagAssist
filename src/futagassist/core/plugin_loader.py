"""Plugin discovery and loading from plugins/ directory."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from futagassist.core.exceptions import PluginLoadError
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import PluginInfo

log = logging.getLogger(__name__)


def _find_plugin_modules(plugin_dir: Path) -> list[Path]:
    """Find all Python modules under plugin_dir (non-private .py files)."""
    modules: list[Path] = []
    if not plugin_dir.is_dir():
        return modules
    for path in plugin_dir.rglob("*.py"):
        if path.name.startswith("_"):
            continue
        modules.append(path)
    return modules


class PluginLoader:
    """Discovers and loads plugins from plugins/ directory."""

    def __init__(
        self,
        plugin_dirs: list[Path],
        registry: ComponentRegistry,
    ) -> None:
        self._plugin_dirs = [Path(d).resolve() for d in plugin_dirs]
        self._registry = registry
        self._loaded: list[PluginInfo] = []

    def discover_plugins(self) -> list[PluginInfo]:
        """Discover all plugins in configured directories."""
        discovered: list[PluginInfo] = []
        for plugin_dir in self._plugin_dirs:
            for mod_path in _find_plugin_modules(plugin_dir):
                rel = mod_path.relative_to(plugin_dir) if plugin_dir in mod_path.parents else mod_path
                plugin_type = mod_path.parent.name if mod_path.parent != plugin_dir else "root"
                discovered.append(
                    PluginInfo(
                        name=mod_path.stem,
                        path=mod_path,
                        module_name=f"futagassist_plugin_{mod_path.stem}_{id(mod_path)}",
                        plugin_type=plugin_type,
                    )
                )
        return discovered

    def load_plugin(self, plugin_path: Path) -> None:
        """Load a single plugin module and call its register(registry)."""
        path = Path(plugin_path).resolve()
        if not path.exists():
            raise PluginLoadError(f"Plugin path does not exist: {path}")

        module_name = f"futagassist_plugin_{path.stem}_{id(path)}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Could not load spec for: {path}")

        try:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
        except Exception as e:
            raise PluginLoadError(f"Failed to load plugin {path}: {e}") from e

        if not hasattr(mod, "register"):
            raise PluginLoadError(f"Plugin has no register() function: {path}")

        try:
            mod.register(self._registry)
        except Exception as e:
            raise PluginLoadError(f"Plugin register() failed for {path}: {e}") from e

        self._loaded.append(
            PluginInfo(
                name=path.stem,
                path=path,
                module_name=module_name,
                plugin_type=path.parent.name,
            )
        )

    def load_all(self) -> list[PluginInfo]:
        """Discover and load all plugins; return list of loaded plugin info.

        Plugins that fail to load are logged as warnings and collected in
        ``self.load_errors`` for later inspection.
        """
        self._loaded = []
        self.load_errors: list[tuple[Path, PluginLoadError]] = []
        for plugin_dir in self._plugin_dirs:
            for mod_path in _find_plugin_modules(plugin_dir):
                try:
                    self.load_plugin(mod_path)
                except PluginLoadError as e:
                    log.warning("Failed to load plugin %s: %s", mod_path, e)
                    self.load_errors.append((mod_path, e))
                    continue
        if self.load_errors:
            log.warning(
                "%d plugin(s) failed to load: %s",
                len(self.load_errors),
                ", ".join(str(p) for p, _ in self.load_errors),
            )
        return list(self._loaded)
