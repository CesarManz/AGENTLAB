
import asyncio

from backend.providers.google import GoogleProvider


async def main():
    provider = GoogleProvider(model="gemini-4-hydrogen")

    try:
        print("Conectando con Gemini 4 Hydrogen...")

        response = await provider.generate(
            "Hola, eres el primer modelo conectado a AGENT LAB. Preséntate brevemente."
        )

        print("\nRespuesta de Gemini:")
        print(response)

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
