import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str


def _parse_route_spec(spec: str, fallback_provider: str) -> ModelRoute:
    """
    Permite definir en .env tanto 'modelo' como 'proveedor:modelo'
    (ej. 'groq:llama-3.3-70b-versatile' o 'openrouter:deepseek/deepseek-r1:free').
    """
    cleaned = spec.strip()
    if ":" in cleaned and not cleaned.startswith("http"):
        maybe_provider, rest = cleaned.split(":", 1)
        if maybe_provider.lower() in {"google", "groq", "openrouter", "deepseek", "ollama"}:
            return ModelRoute(provider=maybe_provider.lower(), model=rest.strip())
    return ModelRoute(provider=fallback_provider.lower(), model=cleaned)


def resolve_model_route(
    model_tier: str,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> ModelRoute:
    """
    Traduce un tier lógico ('fast', 'balanced', 'reasoning') a un proveedor y modelo concreto.
    """
    default_provider = os.getenv("DEFAULT_PROVIDER", "google").lower()
    tier_map = {
        "fast": os.getenv("MODEL_TIER_FAST", "gemini-2.5-flash"),
        "balanced": os.getenv("MODEL_TIER_BALANCED", "gemini-2.5-flash"),
        "reasoning": os.getenv("MODEL_TIER_REASONING", "gemini-2.5-flash"),
    }

    if model_override:
        route = _parse_route_spec(model_override, provider_override or default_provider)
        if provider_override:
            return ModelRoute(provider=provider_override.lower(), model=route.model)
        return route

    raw_spec = tier_map.get(model_tier, tier_map["fast"])
    route = _parse_route_spec(raw_spec, default_provider)
    if provider_override:
        return ModelRoute(provider=provider_override.lower(), model=route.model)
    return route
