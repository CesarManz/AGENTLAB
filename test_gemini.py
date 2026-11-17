import asyncio
from uuid import uuid4

from backend.providers.google import GoogleProvider
from backend.providers.schemas import Message, ToolDefinition


async def main() -> None:
    provider = GoogleProvider(model="gemini-4-hydrogen")

    try:
        print("Conectando con Gemini 4 Hydrogen (contrato v0.2)...")

        user_msg = Message(
            run_id=uuid4(),
            session_id=uuid4(),
            sequence=0,
            role="user",
            content="Lee el archivo README.md usando la herramienta disponible.",
        )

        read_tool = ToolDefinition(
            name="read_file",
            description="Lee el contenido de un archivo de texto dentro del workspace.",
            json_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa del archivo a leer",
                    }
                },
                "required": ["path"],
            },
        )

        response = await provider.generate(
            [user_msg],
            system_instruction="Eres un agente técnico de AGENT LAB. Usa tus herramientas cuando te pidan leer archivos.",
            tools=[read_tool],
        )

        print("\n--- LLMResponse normalizado ---")
        print("Finish reason:", response.finish_reason)
        print("Latencia (ms):", response.latency_ms)
        print("Tokens:", response.usage)
        print("Texto:", response.content)
        print("ToolCalls:", response.tool_calls)

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())