import time
from pathlib import Path

from pydantic import BaseModel, Field

from backend.tools.base import BaseTool
from backend.tools.schemas import RiskLevel, ToolResult
from backend.tools.workspace import BLOCKED_FILENAMES, INTERNAL_META_DIR, WorkspaceManager

MAX_OUTPUT_CHARS = 20_000
IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", INTERNAL_META_DIR}


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
        ws = WorkspaceManager(workspace_path)

        try:
            target = ws.resolve_path(args.path)
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
        ws = WorkspaceManager(workspace_path)

        try:
            target_dir = ws.resolve_path(args.subpath)
            if not target_dir.exists() or not target_dir.is_dir():
                raise FileNotFoundError(f"El directorio '{args.subpath}' no existe en el workspace.")

            entries: list[str] = []
            for item in sorted(target_dir.rglob("*")):
                rel_parts = item.relative_to(ws.root).parts
                if any(part in IGNORED_DIRS for part in rel_parts):
                    continue
                if item.name.lower() in BLOCKED_FILENAMES or item.name.lower().startswith(".env."):
                    continue
                rel = ws.to_relative_posix(item)
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


class WriteFileArgs(BaseModel):
    path: str = Field(
        min_length=1,
        description="Ruta relativa dentro del workspace donde crear o sobrescribir el archivo.",
    )
    content: str = Field(
        description="Contenido completo de texto UTF-8 que se escribirá en el archivo.",
    )


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Crea un archivo nuevo o sobrescribe uno existente dentro del workspace (genera respaldo previo si existía)."
    args_schema = WriteFileArgs
    risk_level: RiskLevel = "moderate"

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        assert isinstance(args, WriteFileArgs)
        start = time.perf_counter()
        ws = WorkspaceManager(workspace_path)

        try:
            target = ws.resolve_path(args.path)
            if target.exists() and target.is_dir():
                raise IsADirectoryError(f"'{args.path}' es un directorio, no se puede sobrescribir como archivo.")

            existed = target.exists()
            backup = ws.create_backup(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.content, encoding="utf-8")

            rel_path = ws.to_relative_posix(target)
            action = "sobrescrito" if existed else "creado"
            backup_note = f" (respaldo en {ws.to_relative_posix(backup)})" if backup else ""
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="success",
                output=f"Archivo '{rel_path}' {action} correctamente ({len(args.content)} caracteres){backup_note}.",
                execution_time_ms=elapsed_ms,
                artifacts_created=[rel_path],
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output=f"Error al escribir '{args.path}': {exc}",
                execution_time_ms=elapsed_ms,
            )


class EditFileArgs(BaseModel):
    path: str = Field(
        min_length=1,
        description="Ruta relativa dentro del workspace del archivo existente a modificar.",
    )
    old_text: str = Field(
        min_length=1,
        description="Fragmento exacto de texto actual que debe ser reemplazado (debe aparecer una única vez).",
    )
    new_text: str = Field(
        description="Nuevo fragmento de texto que reemplazará a old_text.",
    )


class EditFileTool(BaseTool):
    name = "edit_file"
    description = "Reemplaza un bloque exacto y único de texto dentro de un archivo existente en el workspace."
    args_schema = EditFileArgs
    risk_level: RiskLevel = "moderate"

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        assert isinstance(args, EditFileArgs)
        start = time.perf_counter()
        ws = WorkspaceManager(workspace_path)

        try:
            target = ws.resolve_path(args.path)
            if not target.exists() or not target.is_file():
                raise FileNotFoundError(f"El archivo '{args.path}' no existe en el workspace.")

            current_content = target.read_text(encoding="utf-8")
            occurrences = current_content.count(args.old_text)

            if occurrences == 0:
                raise ValueError(
                    f"No se encontró el bloque 'old_text' exacto dentro de '{args.path}'. Lee el archivo primero para verificar su contenido."
                )
            if occurrences > 1:
                raise ValueError(
                    f"El bloque 'old_text' aparece {occurrences} veces en '{args.path}'. Proporciona más contexto para que sea único."
                )

            backup = ws.create_backup(target)
            updated_content = current_content.replace(args.old_text, args.new_text, 1)
            target.write_text(updated_content, encoding="utf-8")

            rel_path = ws.to_relative_posix(target)
            backup_note = f" (respaldo en {ws.to_relative_posix(backup)})" if backup else ""
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="success",
                output=f"Archivo '{rel_path}' editado correctamente{backup_note}.",
                execution_time_ms=elapsed_ms,
                artifacts_created=[rel_path],
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                status="error",
                output=f"Error al editar '{args.path}': {exc}",
                execution_time_ms=elapsed_ms,
            )
