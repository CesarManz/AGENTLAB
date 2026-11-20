import json
from pathlib import Path

from backend.agents.planner import TaskPlanner
from backend.providers.schemas import LLMResponse, TokenUsage
from tests.test_v03_hitl_api import ScriptedMockProvider, _build_test_client


def test_auto_planner_generates_dynamic_multiagent_stages(tmp_path: Path) -> None:
    plan_json = json.dumps(
        {
            "rationale": "Primero exploramos y luego programamos el módulo solicitado.",
            "stages": [
                {
                    "node_id": "n1_scan",
                    "agent_id": "explorador",
                    "instruction": "Revisa archivos existentes en el workspace.",
                },
                {
                    "node_id": "n2_impl",
                    "agent_id": "programador",
                    "instruction": "Crea el archivo 'saludo.py'.",
                },
            ],
        }
    )

    responses = [
        # 1. Respuesta del TaskPlanner
        LLMResponse(
            content=plan_json,
            usage=TokenUsage(input_tokens=50, output_tokens=40, total_tokens=90),
            provider="mock",
            model_name="mock-reasoning",
            finish_reason="stop",
            latency_ms=10,
        ),
        # 2. Respuesta etapa 1 (explorador)
        LLMResponse(
            content="Workspace vacío.",
            usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30),
            provider="mock",
            model_name="mock-fast",
            finish_reason="stop",
            latency_ms=5,
        ),
        # 3. Respuesta etapa 2 (programador)
        LLMResponse(
            content="Módulo saludo.py listo.",
            usage=TokenUsage(input_tokens=30, output_tokens=15, total_tokens=45),
            provider="mock",
            model_name="mock-balanced",
            finish_reason="stop",
            latency_ms=5,
        ),
    ]

    client, ws = _build_test_client(tmp_path, responses)
    container = client.app.state.container
    provider = ScriptedMockProvider(responses)
    container.engine.provider_factory = lambda route: provider
    container.planner = TaskPlanner(
        agent_registry=container.agents,
        repository=container.repo,
        provider_factory=lambda route: provider,
    )

    res = client.post(
        "/pipelines/auto",
        json={
            "user_prompt": "Crea un módulo de saludos en Python",
            "workspace_path": str(ws),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "scheduled"
    assert len(data["planned_stages"]) == 2
    assert data["planned_stages"][0]["agent_id"] == "explorador"
    assert data["planned_stages"][1]["agent_id"] == "programador"
