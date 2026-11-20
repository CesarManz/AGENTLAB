from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import create_app


def test_workspace_files_list_and_read_with_security(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "app.py").write_text("print('hola')\n", encoding="utf-8")
    (ws / ".env").write_text("SECRET=123\n", encoding="utf-8")

    app = create_app(db_path=tmp_path / "ws_test.db")
    with TestClient(app) as client:
        res_list = client.get("/workspace/files", params={"workspace_path": str(ws)})
        assert res_list.status_code == 200
        paths = [f["path"] for f in res_list.json()["files"]]
        assert paths == ["app.py"]

        res_read = client.get(
            "/workspace/file",
            params={"workspace_path": str(ws), "path": "app.py"},
        )
        assert res_read.status_code == 200
        assert res_read.json()["content"] == "print('hola')\n"

        res_forbidden = client.get(
            "/workspace/file",
            params={"workspace_path": str(ws), "path": "../secret.txt"},
        )
        assert res_forbidden.status_code == 403
