import time
from pathlib import Path

from pydantic import BaseModel, Field

from backend.tools.base import BaseTool
from backend.tools.schemas import RiskLevel, ToolResult

MAX_OUTPUT_CHARS = 20_000
BLOCKED_FILENAMES = {".env", "id_rsa", "id_ed25519"}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def _resolve_safe_path(workspace_path: Path, relative_path: str) -> Path:
    """
    Resuelve una ruta relativa dentro del workspace y bloquea escapes (path traversal)
    o acceso a archivos sensibles.
    """
    base = workspace_path.resolve()
    target = (base / relative_path).resolve()

    if not target.is_relative_to(base):
        raise PermissionError(
            f"Acceso denegado: '{relative_path}' intenta salir del workspace permitido."
        )

    name_lower = target.name.lower()
    if (
        name_lower in BLOCKED_FILENAMES
        or name_lower.startswith(".env.")
        or target.suffix.lower() in BLOCKED_SUFFIXES
        or ".git" in target.parts
    ):
        raise PermissionError(
            f"Acceso denegado por política de seguridad al archivo sensible '{relative_path}'."
        )

    return target


class ReadFileArgs(BaseModel):
    path: str = Field(
        min_length=1,
        description="Ruta relativa al workspace del archivo a leer (ej. 'notas.txt' o 'src/app.py')",
    )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Lee el contenido de texto de un archivo ubicado dentro del workspace."
    args_schema = ReadFileArgs
    risk_level: RiskLevel = "safe"

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        assert isinstance(args, ReadFileArgs)
        start = time.perf_counter()

        try:
            target = _resolve_safe_path(workspace_path, args.path)
            if not target.exists():
                raise FileNotFoundError(f"El archivo '{args.path}' no existe en el workspace.")
            if not target.is_file():
                raise IsADirectoryError(f"'{args.path}' es un directorio, no un archivo.")

            content = target.read_text(encoding="utf-8", errors="replace")
            if len(content) > MAX_OUTPUT_CHARS:
                content = (
                    content[:MAX_OUTPUT_CHARS]
                    + f"\n\n[... contenido truncado a {MAX_OUTPUT_CHARS} caracteres ...]"
                )

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="success",
                output=content,
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output=f"Error al leer '{args.path}': {exc}",
                execution_time_ms=elapsed_ms,
            )


class ListFilesArgs(BaseModel):
    subpath: str = Field(
        default=".",
        description="Subcarpeta relativa dentro del workspace a listar (por defecto la raíz '.')",
    )


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "Lista los archivos y subcarpetas disponibles dentro del workspace."
    args_schema = ListFilesArgs
    risk_level: RiskLevel = "safe"

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        assert isinstance(args, ListFilesArgs)
        start = time.perf_counter()

        try:
            target_dir = _resolve_safe_path(workspace_path, args.subpath)
            if not target_dir.exists() or not target_dir.is_dir():
                raise FileNotFoundError(f"El directorio '{args.subpath}' no existe en el workspace.")

            base = workspace_path.resolve()
            entries: list[str] = []
            for item in sorted(target_dir.rglob("*")):
                if any(part in IGNORED_DIRS for part in item.parts):
                    continue
                if item.name.lower() in BLOCKED_FILENAMES or item.name.lower().startswith(".env."):
                    continue
                rel = item.relative_to(base).as_posix()
                entries.append(f"{rel}/" if item.is_dir() else rel)

            output = "\n".join(entries) if entries else "(El workspace está vacío)"
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="success",
                output=output,
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output=f"Error al listar '{args.subpath}': {exc}",
                execution_time_ms=elapsed_ms,
            )