import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from backend.agents.engine import ProviderFactory
from backend.agents.orchestrator import PipelineStage
from backend.agents.registry import AgentRegistry
from backend.agents.schemas import TaskSession
from backend.core.config import resolve_model_route
from backend.core.pricing import estimate_call_cost_usd
from backend.providers.schemas import Message
from backend.storage.repository import StorageRepository
from backend.storage.schemas import TokenLedgerEntry
from backend.tools.filesystem import IGNORED_DIRS
from backend.tools.workspace import BLOCKED_FILENAMES, WorkspaceManager


class PlannedStageDTO(BaseModel):
    node_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1)


class GeneratedPlanDTO(BaseModel):
    rationale: str = Field(default="")
    stages: list[PlannedStageDTO] = Field(min_length=1, max_length=6)


class TaskPlanner:
    """
    Agente planificador que inspecciona el objetivo y el estado inicial del workspace
    para construir dinámicamente un pipeline de etapas especializadas.
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        repository: StorageRepository,
        provider_factory: ProviderFactory,
    ) -> None:
        self.agents = agent_registry
        self.repo = repository
        self.provider_factory = provider_factory

    def _summarize_workspace(self, workspace_path: str) -> str:
        ws = WorkspaceManager(workspace_path)
        files: list[str] = []
        for item in sorted(ws.root.rglob("*")):
            if not item.is_file():
                continue
            rel_parts = item.relative_to(ws.root).parts
            if any(part in IGNORED_DIRS for part in rel_parts):
                continue
            if item.name.lower() in BLOCKED_FILENAMES or item.name.lower().startswith(".env."):
                continue
            files.append(ws.to_relative_posix(item))

        if not files:
            return "(Workspace vacío)"
        return "\n".join(f"- {f}" for f in files[:40])

    def _fallback_stages(self) -> list[PipelineStage]:
        stages: list[PipelineStage] = []
        available = {a.id for a in self.agents.list_all()}
        if "explorador" in available:
            stages.append(
                PipelineStage(
                    node_id="node_01_explorer",
                    agent_id="explorador",
                    instruction="Inspecciona el workspace y publica un diagnóstico técnico en el Blackboard.",
                )
            )
        if "programador" in available:
            stages.append(
                PipelineStage(
                    node_id="node_02_builder",
                    agent_id="programador",
                    instruction="Implementa la solución solicitada en el objetivo global y verifica su funcionamiento.",
                )
            )
        if not stages:
            first_agent = self.agents.list_all()[0]
            stages.append(
                PipelineStage(
                    node_id="node_01_primary",
                    agent_id=first_agent.id,
                    instruction="Ejecuta el objetivo solicitado por el usuario.",
                )
            )
        return stages

    async def build_plan(self, session: TaskSession) -> tuple[list[PipelineStage], str]:
        """
        Genera y valida una lista de PipelineStage para la sesión dada.
        Devuelve (stages, rationale).
        """
        available_agents = [
            a for a in self.agents.list_all() if a.id != "planner"
        ]
        valid_ids = {a.id for a in available_agents}

        agents_catalog = "\n".join(
            f"- id='{a.id}' ({a.name} — {a.role}): {a.description or a.system_prompt[:140]}"
            for a in available_agents
        )
        workspace_summary = self._summarize_workspace(session.workspace_path)

        system_prompt = (
            "Eres el Arquitecto Planificador de AGENT LAB. "
            "Tu única función es descomponer la solicitud del usuario en un pipeline secuencial de 1 a 5 etapas "
            "asignando el agente especialista más adecuado a cada etapa.\n"
            "Responde EXCLUSIVAMENTE con un objeto JSON válido con este formato exacto:\n"
            '{"rationale": "breve explicación del plan", "stages": [{"node_id": "node_01_...", "agent_id": "...", "instruction": "..."}]}\n'
            "Reglas estrictas:\n"
            f"1. 'agent_id' DEBE ser exactamente uno de: {sorted(valid_ids)}.\n"
            "2. Si la tarea requiere crear o modificar código, incluye normalmente exploración previa (si hay archivos), "
            "implementación/tests ('programador') y auditoría ('revisor') si aporta valor.\n"
            "3. Si la tarea es solo lectura, análisis o auditoría, NO incluyas etapas de escritura innecesarias."
        )

        user_content = (
            f"Solicitud del usuario:\n{session.user_prompt}\n\n"
            f"Agentes disponibles:\n{agents_catalog}\n\n"
            f"Archivos actuales en el workspace:\n{workspace_summary}"
        )

        route = resolve_model_route("reasoning")
        provider = self.provider_factory(route)
        plan_run_id = uuid4()

        try:
            response = await provider.generate(
                [
                    Message(
                        run_id=plan_run_id,
                        session_id=session.id,
                        sequence=0,
                        role="user",
                        content=user_content,
                    )
                ],
                system_instruction=system_prompt,
                temperature=0.1,
                response_schema=GeneratedPlanDTO.model_json_schema(),
            )

            # Registrar el consumo del planificador si la sesión ya existe en DB
            if self.repo.get_session(session.id) is not None:
                cost = estimate_call_cost_usd(
                    provider=response.provider,
                    model_name=response.model_name,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cached_tokens=response.usage.cached_tokens,
                )
                self.repo.record_token_usage(
                    TokenLedgerEntry(
                        session_id=session.id,
                        run_id=plan_run_id,
                        agent_id="planner",
                        provider=response.provider,
                        model_name=response.model_name,
                        step_number=0,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        cached_tokens=response.usage.cached_tokens,
                        total_tokens=response.usage.total_tokens,
                        estimated_cost_usd=cost,
                        latency_ms=response.latency_ms,
                    )
                )

            raw_dict = response.parsed_output
            if raw_dict is None and response.content:
                cleaned = response.content.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.strip("`")
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:].strip()
                raw_dict = json.loads(cleaned)

            if not isinstance(raw_dict, dict):
                return self._fallback_stages(), "Plan de respaldo estándar (respuesta no estructurada)."

            parsed = GeneratedPlanDTO.model_validate(raw_dict)
            filtered = [
                PipelineStage(
                    node_id=s.node_id,
                    agent_id=s.agent_id,
                    instruction=s.instruction,
                )
                for s in parsed.stages
                if s.agent_id in valid_ids
            ]

            if not filtered:
                return self._fallback_stages(), "Plan de respaldo estándar (ningún agent_id válido)."

            return filtered, parsed.rationale or "Plan generado dinámicamente por TaskPlanner."

        except (ValidationError, json.JSONDecodeError, Exception):
            return self._fallback_stages(), "Plan de respaldo estándar aplicado automáticamente."
        finally:
            await provider.close()
