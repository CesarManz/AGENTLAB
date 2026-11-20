from backend.tools.git_ops import GitSafetyManager
from backend.tools.knowledge_graph import ASTKnowledgeGraph
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
from backend.tools.filesystem import IGNORED_DIRS
from backend.tools.workspace import BLOCKED_FILENAMES, WorkspaceManager


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
        app.state.container.repo.recover_interrupted_sessions()
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

    @app.get("/workspace/files")
    async def list_workspace_files(workspace_path: str = "data/live_workspace") -> dict[str, Any]:
        ws = WorkspaceManager(workspace_path)
        files: list[dict[str, Any]] = []
        for item in sorted(ws.root.rglob("*")):
            if not item.is_file():
                continue
            rel_parts = item.relative_to(ws.root).parts
            if any(part in IGNORED_DIRS for part in rel_parts):
                continue
            if item.name.lower() in BLOCKED_FILENAMES or item.name.lower().startswith(".env."):
                continue
            files.append(
                {
                    "path": ws.to_relative_posix(item),
                    "size_bytes": item.stat().st_size,
                }
            )
        return {"workspace_path": str(ws.root), "files": files}

    @app.get("/workspace/file")
    async def read_workspace_file(
        path: str, workspace_path: str = "data/live_workspace"
    ) -> dict[str, Any]:
        ws = WorkspaceManager(workspace_path)
        try:
            target = ws.resolve_path(path)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail=f"Archivo '{path}' no encontrado.")

        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "path": ws.to_relative_posix(target),
            "content": content,
        }

    @app.get("/sessions")
    async def list_sessions(request: Request) -> dict[str, Any]:
        c = get_container(request)
        sessions = c.repo.list_sessions(limit=25)
        pending = c.repo.list_pending_approvals()
        return {
            "sessions": [s.model_dump(mode="json") for s in sessions],
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
            "total_cost_usd": c.repo.get_total_cost_usd(),
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
        session.git_checkpoint = GitSafetyManager(session.workspace_path).create_checkpoint(str(session.id))
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
        session.git_checkpoint = GitSafetyManager(session.workspace_path).create_checkpoint(str(session.id))
        background_tasks.add_task(c.engine.execute_session, session, body.agent_id)

        return {
            "session_id": str(session.id),
            "ws_url": f"/ws/sessions/{session.id}",
            "status": "scheduled",
        }

    @app.post("/pipelines/auto")
    async def run_auto_pipeline_async(
        body: dict[str, Any],
        background_tasks: BackgroundTasks,
        request: Request,
    ) -> dict[str, Any]:
        c = get_container(request)
        session = TaskSession(
            user_prompt=body["user_prompt"],
            workspace_path=body.get("workspace_path", "data/default_workspace"),
            use_knowledge_graph=bool(body.get("use_knowledge_graph", False)),
            max_budget_tokens=body.get("max_budget_tokens", 40_000),
        )
        session.git_checkpoint = GitSafetyManager(session.workspace_path).create_checkpoint(str(session.id))
        if session.use_knowledge_graph:
            kg = ASTKnowledgeGraph(session.workspace_path)
            kg.index_workspace()
            session.blackboard["ast_code_graph"] = kg.render_compact_map()
        stages, rationale = await c.planner.build_plan(session)
        session.blackboard["planner_rationale"] = rationale
        background_tasks.add_task(c.orchestrator.run_pipeline, session, stages)
        return {
            "session_id": str(session.id),
            "ws_url": f"/ws/sessions/{session.id}",
            "status": "scheduled",
            "rationale": rationale,
            "planned_stages": [
                {"node_id": s.node_id, "agent_id": s.agent_id, "instruction": s.instruction}
                for s in stages
            ],
        }

    @app.post("/pipelines/async")
    async def run_pipeline_async(
        body: dict[str, Any],
        background_tasks: BackgroundTasks,
        request: Request,
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
        background_tasks.add_task(c.orchestrator.run_pipeline, session, stages)
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

    @app.post("/sessions/{session_id}/rollback")
    async def rollback_session(session_id: UUID, request: Request) -> dict[str, Any]:
        c = get_container(request)
        session = c.repo.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        mgr = GitSafetyManager(session.workspace_path)
        res = mgr.rollback_mission(session.git_checkpoint)
        return res.model_dump(mode="json")

    @app.post("/sessions/{session_id}/resume")
    async def resume_session(session_id: UUID, request: Request) -> dict[str, Any]:
        c = get_container(request)
        try:
            runs = await c.orchestrator.resume_interrupted_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        updated_session = c.repo.get_session(session_id)
        pending = c.repo.list_pending_approvals(session_id)
        return {
            "session": updated_session.model_dump(mode="json") if updated_session else None,
            "runs": [r.model_dump(mode="json") for r in runs],
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
        }

    @app.delete("/sessions/{session_id}")
    async def delete_session_endpoint(session_id: UUID, request: Request) -> dict[str, Any]:
        c = get_container(request)
        deleted = c.repo.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        return {"status": "deleted", "session_id": str(session_id)}

    @app.delete("/sessions")
    async def clear_sessions_endpoint(request: Request) -> dict[str, Any]:
        c = get_container(request)
        count = c.repo.clear_sessions()
        return {"status": "cleared", "deleted_count": count}

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
            "session_cost_usd": c.repo.get_session_cost_usd(session_id),
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

        if run.status == "completed":
            resumed_runs = await c.orchestrator.resume_pipeline_if_needed(run.session_id)
            if resumed_runs:
                run = resumed_runs[-1]

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






