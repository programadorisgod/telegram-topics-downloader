"""Contrato que todo plugin de knw debe implementar."""

from abc import ABC, abstractmethod


class Plugin(ABC):
    name: str = "base"

    @abstractmethod
    def router(self):
        """Devuelve un fastapi.APIRouter con los endpoints del plugin."""
        ...

    def build(self):
        """Setup opcional al arrancar (indexar, conectar, etc.)."""
        return None
