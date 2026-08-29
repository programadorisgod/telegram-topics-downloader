"""Contrato de proveedor de chat, agnóstico al modelo.

La app/plugin NUNCA importa un proveedor concreto: resuelve por env
`KNW_AI_PROVIDER`. Hoy solo hay deepseek; agregar otro = una clase nueva
aquí + un case en `get_provider()`, sin tocar la orquestación.
"""

import importlib
from abc import ABC, abstractmethod


class ChatProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(self, system: str, messages: list[dict], **kwargs) -> str:
        """Devuelve el texto de la respuesta del modelo.

        messages: lista [{"role": "user"|"assistant", "content": str}, ...]
        """
        ...


class ProviderConfigError(Exception):
    """Falta configuración del proveedor (p.ej. API key), no un fallo de red."""
_providers: dict[str, type[ChatProvider]] = {}


def register(cls: type[ChatProvider]) -> type[ChatProvider]:
    _providers[cls.name] = cls
    return cls


def get_provider(name: str | None = None) -> ChatProvider:
    name = name or "deepseek"  # default probable
    if name not in _providers:
        try:
            # import side-effect del módulo concreto registra la clase
            importlib.import_module(f"providers.{name}")
        except ImportError:
            pass
    if name not in _providers:
        raise ValueError(f"Proveedor '{name}' no registrado. Disponibles: {sorted(_providers)}")
    return _providers[name]()
