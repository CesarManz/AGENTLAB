from dotenv import load_dotenv
import os

from google import genai

from backend.providers.base import BaseProvider

load_dotenv()

class GoogleProvider(BaseProvider):
    """
    Proveedor encargado de comunicarse con los modelos Gemini.
    """

    def __init__(self, model: str, api_key: str | None = None):
        self.model = model

        # Obtener la API Key desde el entorno
        api_key = api_key or os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("No se encontró GEMINI_API_KEY")

        # Crear cliente de Google y su interfaz asíncrona
        self._client = genai.Client(api_key=api_key)
        self._async_client = self._client.aio

    async def generate(self, prompt: str) -> str:
        """
        Envía un prompt a Gemini y devuelve su respuesta.
        """

        response = await self._async_client.models.generate_content(
            model=self.model,
            contents=prompt
        )

        return response.text or ""

    async def close(self):
        """
        Cierra la conexión con Google.
        """

        await self._async_client.aclose()
