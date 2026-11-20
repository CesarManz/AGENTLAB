import asyncio
import os
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

from backend.tools.base import BaseTool
from backend.tools.schemas import RiskLevel, ToolResult
from backend.tools.workspace import WorkspaceManager

MAX_TEST_OUTPUT_CHARS = 15_000

_ALLOWED_ENV_KEYS = frozenset(
    {
        "PATH",
        "SYSTEMROOT",
        "COMSPEC",
        "WINDIR",
        "TEMP",
        "TMP",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "LANG",
        "LC_ALL",
        "HOME",
        "USERPROFILE",
    }
)

_SENSITIVE_SUBSTRINGS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH")


def build_restricted_env() -> dict[str, str]:
    """
    Construye un entorno de variables mínimo y sanitizado para subprocesos.

    NOTA DE ARQUITECTURA (Alcance y Limitaciones):
    - Esta función implementa *ejecución con entorno restringido* (allowlist estricta de variables
      de sistema y bloqueo explícito de secretos como GEMINI_API_KEY, GROQ_API_KEY, etc.).
    - NO constituye un sandbox a nivel de sistema operativo: el proceso hijo aún comparte
      el sistema de archivos y la red del usuario hasta que se integre aislamiento por contenedor/OS.
    """
    restricted: dict[str, str] = {}
    for k, v in os.environ.items():
        upper_k = k.upper()
        if any(sub in upper_k for sub in _SENSITIVE_SUBSTRINGS):
            continue
        if upper_k in _ALLOWED_ENV_KEYS:
            restricted[k] = v

    restricted["AGENTLAB_RESTRICTED_ENV"] = "1"
    restricted["PYTHONDONTWRITEBYTECODE"] = "1"
    return restricted


class RunPytestArgs(BaseModel):
    target_path: str = Field(
        default=".",
        description="Ruta relativa dentro del workspace del archivo o carpeta de tests a ejecutar con pytest (por defecto '.').",
    )


class RunPytestTool(BaseTool):
    name = "run_pytest"
    description = (
        "Ejecuta la suite de pruebas pytest sobre un archivo o carpeta dentro del workspace "
        "bajo un entorno de variables restringido (sin credenciales del servidor). "
        "Requiere aprobación humana explícita y tiene un límite de tiempo de 30 segundos."
    )
    args_schema = RunPytestArgs
    risk_level: RiskLevel = "critical"
    timeout_seconds: int = 30

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        assert isinstance(args, RunPytestArgs)
        start = time.perf_counter()
        ws = WorkspaceManager(workspace_path)

        try:
            resolved_target = ws.resolve_path(args.target_path)
            if not resolved_target.exists():
                raise FileNotFoundError(
                    f"La ruta de tests '{args.target_path}' no existe dentro del workspace."
                )

            rel_target = ws.to_relative_posix(resolved_target)
            cmd = [sys.executable, "-m", "pytest", rel_target, "-v", "--tb=short"]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ws.root),
                env=build_restricted_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=float(self.timeout_seconds),
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    status="timeout",
                    output=f"Timeout: pytest excedió el límite de {self.timeout_seconds}s y fue terminado.",
                    execution_time_ms=elapsed_ms,
                )

            stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

            combined = stdout_text
            if stderr_text:
                combined = f"{combined}\n\n[STDERR]\n{stderr_text}".strip()
            if not combined:
                combined = "(pytest no produjo salida)"

            if len(combined) > MAX_TEST_OUTPUT_CHARS:
                combined = (
                    combined[:MAX_TEST_OUTPUT_CHARS]
                    + f"\n\n[... salida truncada a {MAX_TEST_OUTPUT_CHARS} caracteres ...]"
                )

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if proc.returncode == 0:
                status = "success"
            else:
                status = "error"
                combined = f"[EXIT CODE {proc.returncode}]\n{combined}"

            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status=status,
                output=combined,
                execution_time_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output=f"Error al ejecutar pytest en '{args.target_path}': {exc}",
                execution_time_ms=elapsed_ms,
            )