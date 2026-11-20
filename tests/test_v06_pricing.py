from backend.core.pricing import estimate_call_cost_usd


def test_pricing_calculates_usd_and_respects_free_tiers() -> None:
    # Modelo gratuito en OpenRouter o local en Ollama -> $0.0
    assert (
        estimate_call_cost_usd(
            provider="openrouter",
            model_name="deepseek/deepseek-r1:free",
            input_tokens=10_000,
            output_tokens=5_000,
        )
        == 0.0
    )
    assert (
        estimate_call_cost_usd(
            provider="ollama",
            model_name="qwen2.5-coder:7b",
            input_tokens=10_000,
            output_tokens=5_000,
        )
        == 0.0
    )

    # Cálculo con tarifa de referencia (openai/gpt-oss-120b: $0.15 in / $0.60 out por 1M)
    cost = estimate_call_cost_usd(
        provider="groq",
        model_name="openai/gpt-oss-120b",
        input_tokens=1_000_000,
        output_tokens=500_000,
    )
    assert cost == 0.45
