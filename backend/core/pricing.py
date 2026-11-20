from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m_usd: float
    output_per_1m_usd: float
    cached_per_1m_usd: float = 0.0


# Tarifas de referencia por 1,000,000 de tokens (USD).
# Modelos ':free' y 'ollama' tienen coste $0.00.
MODEL_PRICING_TABLE: dict[str, ModelPricing] = {
    "gemini-2.5-flash": ModelPricing(input_per_1m_usd=0.15, output_per_1m_usd=0.60, cached_per_1m_usd=0.0375),
    "gemini-2.5-pro": ModelPricing(input_per_1m_usd=1.25, output_per_1m_usd=10.00, cached_per_1m_usd=0.31),
    "gemini-4-hydrogen": ModelPricing(input_per_1m_usd=0.0, output_per_1m_usd=0.0),
    "deepseek-chat": ModelPricing(input_per_1m_usd=0.27, output_per_1m_usd=1.10, cached_per_1m_usd=0.07),
    "deepseek-reasoner": ModelPricing(input_per_1m_usd=0.55, output_per_1m_usd=2.19, cached_per_1m_usd=0.14),
    "openai/gpt-oss-20b": ModelPricing(input_per_1m_usd=0.075, output_per_1m_usd=0.30),
    "openai/gpt-oss-120b": ModelPricing(input_per_1m_usd=0.15, output_per_1m_usd=0.60),
    "qwen/qwen3.8-27b": ModelPricing(input_per_1m_usd=0.10, output_per_1m_usd=0.40),
}


def estimate_call_cost_usd(
    *,
    provider: str,
    model_name: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None = None,
) -> float:
    """
    Calcula el coste estimado en USD de una llamada LLM según proveedor, modelo y tokens.
    """
    pid = provider.lower().strip()
    mname = model_name.lower().strip()

    if pid == "ollama" or mname.endswith(":free"):
        return 0.0

    pricing = MODEL_PRICING_TABLE.get(mname)
    if pricing is None:
        for key, candidate in MODEL_PRICING_TABLE.items():
            if key in mname:
                pricing = candidate
                break

    if pricing is None:
        return 0.0

    in_tok = max(0, input_tokens or 0)
    out_tok = max(0, output_tokens or 0)
    cache_tok = max(0, cached_tokens or 0)
    billable_in = max(0, in_tok - cache_tok)

    cost = (
        (billable_in / 1_000_000.0) * pricing.input_per_1m_usd
        + (cache_tok / 1_000_000.0) * pricing.cached_per_1m_usd
        + (out_tok / 1_000_000.0) * pricing.output_per_1m_usd
    )
    return round(cost, 6)
