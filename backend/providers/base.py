
from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """
    Contrato base para todos los proveedores de IA.
    """

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """
        Recibe un prompt y devuelve la respuesta del modelo.
        """
        pass
