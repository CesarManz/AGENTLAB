from pathlib import Path

from backend.providers.schemas import LLMResponse, TokenUsage, ToolCall
from tests.test_v03_hitl_api import _build_test_client


def test_pipeline_resumes_remaining_stages_after_hitl_approval(tmp_path: Path) -> None:
    responses = [
        # Etapa 1 (explorador): analiza y completa
        LLMResponse(
            content="Workspace listo.",
            usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30),
            provider="mock",
            model_name="mock-v1",
            finish_reason="stop",
            latency_ms=5,
        ),
        # Etapa 2 (programador): pide escribir archivo -> HITL
        LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_write_mod",
                    tool_name="write_file",
                    arguments={"path": "servicio.py", "content": "OK = True\n"},
                ),
            ),
            usage=TokenUsage(input_tokens=30, output_tokens=15, total_tokens=45),
            provider="mock",
            model_name="mock-v1",
            finish_reason="tool_calls",
            latency_ms=5,
        ),
        # Etapa 2 (programador tras aprobar): cierra su etapa
        LLMResponse(
            content="Archivo servicio.py creado.",
            usage=TokenUsage(input_tokens=40, output_tokens=10, total_tokens=50),
            provider="mock",
            model_name="mock-v1",
            finish_reason="stop",
            latency_ms=5,
        ),
        # Etapa 3 (explorador/revisor): debe ejecutarse AUTOMÁTICAMENTE tras la aprobación
        LLMResponse(
            content="Auditoría final aprobada sin errores.",
            usage=TokenUsage(input_tokens=50, output_tokens=15, total_tokens=65),
            provider="mock",
            model_name="mock-v1",
            finish_reason="stop",
            latency_ms=5,
        ),
    ]

    client, ws = _build_test_client(tmp_path, responses)

    res1 = client.post(
        "/pipelines",
        json={
            "user_prompt": "Construye y audita servicio.py",
            "workspace_path": str(ws),
            "stages": [
                {"node_id": "n1_explore", "agent_id": "explorador", "instruction": "Explora"},
                {"node_id": "n2_code", "agent_id": "programador", "instruction": "Escribe servicio.py"},
                {"node_id": "n3_audit", "agent_id": "explorador", "instruction": "Audita el resultado"},
            ],
        },
    )
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["session"]["status"] == "awaiting_approval"
    assert len(d1["runs"]) == 2
    exec_id = d1["pending_approvals"][0]["id"]

    # Al aprobar, debe completar n2_code Y continuar automáticamente con n3_audit
    res2 = client.post(f"/approvals/{exec_id}", json={"approved": True})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["session"]["status"] == "completed"
    assert "Auditoría final aprobada" in (d2["session"]["final_output"] or "")

    full_state = client.get(f"/sessions/{d1['session']['id']}").json()
    assert len(full_state["runs"]) == 3
    assert [r["dag_node_id"] for r in full_state["runs"]] == ["n1_explore", "n2_code", "n3_audit"]
