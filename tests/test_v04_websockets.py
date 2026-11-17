from pathlib import Path

from backend.providers.schemas import LLMResponse, TokenUsage, ToolCall
from tests.test_v03_hitl_api import _build_test_client


def test_websocket_streams_session_events_in_realtime(tmp_path: Path) -> None:
    responses = [
        LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="ws_call_1",
                    tool_name="write_file",
                    arguments={"path": "hello.txt", "content": "hola ws"},
                ),
            ),
            usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30),
            provider="mock",
            model_name="mock-v1",
            finish_reason="tool_calls",
            latency_ms=5,
        )
    ]
    client, ws_dir = _build_test_client(tmp_path, responses)

    res = client.post(
        "/sessions/async",
        json={
            "agent_id": "programador",
            "user_prompt": "Crea hello.txt",
            "workspace_path": str(ws_dir),
        },
    )
    assert res.status_code == 200
    session_id = res.json()["session_id"]

    received_types: list[str] = []
    with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
        while True:
            msg = websocket.receive_json()
            ev_type = msg["event_type"]
            received_types.append(ev_type)
            if ev_type == "APPROVAL_REQUIRED":
                assert msg["payload"]["tool_name"] == "write_file"
                break

    assert received_types == [
        "WS_CONNECTED",
        "SESSION_STARTED",
        "RUN_STARTED",
        "TOKEN_RECORDED",
        "APPROVAL_REQUIRED",
    ]
