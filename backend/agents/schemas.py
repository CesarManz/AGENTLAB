
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """
    Define la configuración básica de un agente de AGENT LAB.
    """

    id: str = Field(
        description="Identificador único del agente"
    )

    name: str = Field(
        min_length=1,
        description="Nombre visible del agente"
    )

    role: str = Field(
        min_length=1,
        description="Función o especialidad del agente"
    )

    description: str = Field(
        min_length=1,
        description="Descripción de las responsabilidades del agente"
    )

    system_prompt: str = Field(
        min_length=1,
        description="Instrucciones principales que definen el comportamiento del agente"
    )

    provider: str = Field(
        min_length=1,
        description="Proveedor del modelo de inteligencia artificial"
    )

    model: str = Field(
        min_length=1,
        description="Identificador del modelo de inteligencia artificial"
    )
