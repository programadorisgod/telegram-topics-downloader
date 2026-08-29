"""Registro de plugins de knw.

La app no conoce ningún plugin por nombre: solo pide al registry
`get(<nombre>)` y monta sus routes. Cada plugin implementa el contrato
de `plugins/base.py`.
"""

import importlib
import pkgutil
from pathlib import Path

from plugins.base import Plugin


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._load()

    def _load(self):
        pkg_dir = Path(__file__).parent
        for mod in pkgutil.iter_modules([str(pkg_dir)]):
            name = mod.name
            if name == "base":
                continue
            try:
                module = importlib.import_module(f"plugins.{name}")
                plugin = getattr(module, "plugin", None)
                if isinstance(plugin, Plugin):
                    self._plugins[plugin.name] = plugin
            except Exception as e:  # un plugin roto no tumba la app
                print(f"[registry] falló al cargar plugin '{name}': {e}")

    def build_all(self):
        for p in self._plugins.values():
            try:
                p.build()
            except Exception as e:
                print(f"[registry] build de '{p.name}' falló: {e}")

    def get(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def names(self) -> list[str]:
        return sorted(self._plugins)


registry = PluginRegistry()
