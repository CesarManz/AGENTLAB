from pathlib import Path

from backend.providers.schemas import LLMResponse, TokenUsage, ToolCall
from tests.test_v03_hitl_api import _build_test_client


def test_multiagent_pipeline_shares_blackboard_and_budget(tmp_path: Path) -> None:
    responses = [
        # Etapa 1 (explorador): publica hallazgo en Blackboard y termina
        LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="bb_write_1",
                    tool_name="write_blackboard",
                    arguments={"key": "stack", "value": "Python + FastAPI"},
                ),
            ),
            usage=TokenUsage(input_tokens=30, output_tokens=15, total_tokens=45),
            provider="mock",
            model_name="mock-v1",
            finish_reason="tool_calls",
            latency_ms=5,
        ),
        LLMResponse(
            content="Hallazgo publicado en el Blackboard.",
            usage=TokenUsage(input_tokens=40, output_tokens=10, total_tokens=50),
            provider="mock",
            model_name="mock-v1",
            finish_reason="stop",
            latency_ms=5,
        ),
        # Etapa 2 (programador): lee Blackboard y entrega respuesta final
        LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="bb_read_1",
                    tool_name="read_blackboard",
                    arguments={"key": "stack"},
                ),
            ),
            usage=TokenUsage(input_tokens=35, output_tokens=15, total_tokens=50),
            provider="mock",
            model_name="mock-v1",
            finish_reason="tool_calls",
            latency_ms=5,
        ),
        LLMResponse(
            content="Confirmado desde Blackboard: el stack es Python + FastAPI.",
            usage=TokenUsage(input_tokens=55, output_tokens=20, total_tokens=75),
            provider="mock",
            model_name="mock-v1",
            finish_reason="stop",
            latency_ms=5,
        ),
    ]
    client, ws = _build_test_client(tmp_path, responses)

    res = client.post(
        "/pipelines",
        json={
            "user_prompt": "Analiza el stack y documenta",
            "workspace_path": str(ws),
            "max_budget_tokens": 1000,
            "stages": [
                {"node_id": "fase_1", "agent_id": "explorador", "instruction": "Detecta el stack"},
                {"node_id": "fase_2", "agent_id": "programador", "instruction": "Lee el stack y resume"},
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["session"]["status"] == "completed"
    assert data["session"]["blackboard"] == {"stack": "Python + FastAPI"}
    assert data["session"]["total_tokens_used"] == 220
    assert len(data["runs"]) == 2
    assert data["runs"][1]["parent_run_id"] == data["runs"][0]["id"]
