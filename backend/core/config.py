import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str


def resolve_model_route(
    model_tier: str,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> ModelRoute:
    """
    Traduce un tier lógico ('fast', 'balanced', 'reasoning') a un proveedor y modelo concreto,
    respetando los overrides explícitos del AgentConfig.
    """
    default_provider = os.getenv("DEFAULT_PROVIDER", "google")
    tier_map = {
        "fast": os.getenv("MODEL_TIER_FAST", "gemini-4-hydrogen"),
        "balanced": os.getenv("MODEL_TIER_BALANCED", "gemini-4-hydrogen"),
        "reasoning": os.getenv("MODEL_TIER_REASONING", "gemini-4-hydrogen"),
    }

    provider = provider_override or default_provider
    model = model_override or tier_map.get(model_tier, tier_map["fast"])
    return ModelRoute(provider=provider, model=model)