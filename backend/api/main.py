import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.agents.orchestrator import PipelineStage
from backend.agents.schemas import TaskSession
from backend.api.dependencies import AppContainer, build_container


class CreateSessionRequest(BaseModel):
    agent_id: str = Field(default="programador", min_length=1)
    user_prompt: str = Field(min_length=1)
    workspace_path: str = Field(default="data/default_workspace", min_length=1)
    max_budget_tokens: int = Field(default=20_000, gt=0)


class ApprovalDecisionRequest(BaseModel):
    approved: bool


def create_app(db_path: str | Path = "data/agent_lab.db") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not hasattr(app.state, "container"):
            app.state.container = build_container(db_path=db_path)
        yield

    app = FastAPI(title="AGENT LAB API", version="0.4.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_container(request: Request) -> AppContainer:
        return request.app.state.container

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        c = get_container(request)
        return {
            "status": "ok",
            "version": "0.5.0",
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "role": a.role,
                    "model_tier": a.model_tier,
                    "allowed_tools": list(a.allowed_tools),
                }
                for a in c.agents.list_all()
            ],
            "tools": [t.name for t in c.tools.list_all()],
        }

    @app.get("/sessions")
    async def list_sessions(request: Request) -> dict[str, Any]:
        c = get_container(request)
        sessions = c.repo.list_sessions(limit=25)
        pending = c.repo.list_pending_approvals()
        return {
            "sessions": [s.model_dump(mode="json") for s in sessions],
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
        }

    @app.post("/sessions")
    async def create_session(
        body: CreateSessionRequest, request: Request
    ) -> dict[str, Any]:
        c = get_container(request)
        try:
            c.agents.get(body.agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        session = TaskSession(
            user_prompt=body.user_prompt,
            workspace_path=body.workspace_path,
            max_budget_tokens=body.max_budget_tokens,
        )
        run = await c.engine.execute_session(session, agent_id=body.agent_id)
        updated_session = c.repo.get_session(session.id)
        pending = c.repo.list_pending_approvals(session.id)

        return {
            "session": updated_session.model_dump(mode="json") if updated_session else None,
            "run": run.model_dump(mode="json"),
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
        }

    @app.post("/sessions/async")
    async def create_session_async(
        body: CreateSessionRequest,
        background_tasks: BackgroundTasks,
        request: Request,
    ) -> dict[str, Any]:
        c = get_container(request)
        try:
            c.agents.get(body.agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        session = TaskSession(
            user_prompt=body.user_prompt,
            workspace_path=body.workspace_path,
            max_budget_tokens=body.max_budget_tokens,
        )
        background_tasks.add_task(c.engine.execute_session, session, body.agent_id)

        return {
            "session_id": str(session.id),
            "ws_url": f"/ws/sessions/{session.id}",
            "status": "scheduled",
        }

    @app.post("/pipelines")
    async def run_pipeline(
        body: dict[str, Any], request: Request
    ) -> dict[str, Any]:
        c = get_container(request)
        raw_stages = body.get("stages") or []
        stages = [
            PipelineStage(
                node_id=s["node_id"],
                agent_id=s["agent_id"],
                instruction=s["instruction"],
            )
            for s in raw_stages
        ]
        session = TaskSession(
            user_prompt=body["user_prompt"],
            workspace_path=body.get("workspace_path", "data/default_workspace"),
            max_budget_tokens=body.get("max_budget_tokens", 25_000),
        )
        runs = await c.orchestrator.run_pipeline(session, stages)
        updated_session = c.repo.get_session(session.id)
        pending = c.repo.list_pending_approvals(session.id)
        return {
            "session": updated_session.model_dump(mode="json") if updated_session else None,
            "runs": [r.model_dump(mode="json") for r in runs],
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
        }

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: UUID, request: Request) -> dict[str, Any]:
        c = get_container(request)
        session = c.repo.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Sesión {session_id} no encontrada.")

        runs = c.repo.list_runs_for_session(session_id)
        pending = c.repo.list_pending_approvals(session_id)
        return {
            "session": session.model_dump(mode="json"),
            "runs": [r.model_dump(mode="json") for r in runs],
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
        }

    @app.get("/sessions/{session_id}/messages")
    async def get_session_messages(session_id: UUID, request: Request) -> dict[str, Any]:
        c = get_container(request)
        session = c.repo.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Sesión {session_id} no encontrada.")

        runs = c.repo.list_runs_for_session(session_id)
        messages = []
        for run in runs:
            messages.extend(m.model_dump(mode="json") for m in c.repo.list_messages(run.id))

        return {"session_id": str(session_id), "messages": messages}

    @app.post("/approvals/{execution_id}")
    async def resolve_approval(
        execution_id: UUID, body: ApprovalDecisionRequest, request: Request
    ) -> dict[str, Any]:
        c = get_container(request)
        try:
            run = await c.engine.resolve_approval(execution_id, approved=body.approved)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        updated_session = c.repo.get_session(run.session_id)
        pending = c.repo.list_pending_approvals(run.session_id)
        return {
            "session": updated_session.model_dump(mode="json") if updated_session else None,
            "run": run.model_dump(mode="json"),
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
        }

    @app.websocket("/ws/sessions/{session_id}")
    async def session_events_ws(websocket: WebSocket, session_id: UUID) -> None:
        c: AppContainer = websocket.app.state.container
        await c.ws_manager.connect(session_id, websocket)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
                    if data.strip().lower() == "ping":
                        await websocket.send_json({"event_type": "PONG"})
                except TimeoutError:
                    continue
        except WebSocketDisconnect:
            c.ws_manager.disconnect(session_id, websocket)

    return app


app = create_app()



