import asyncio
import difflib
import hashlib
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.tools.base import BaseTool
from backend.tools.schemas import RiskLevel, ToolResult
from backend.tools.workspace import BLOCKED_FILENAMES, WorkspaceManager

MAX_DIFF_CHARS = 15_000


class GitCheckpoint(BaseModel):
    """
    Instantánea no destructiva del estado inicial del repositorio antes de ejecutar una misión.
    Permite aislar cambios en una rama y revertir únicamente las modificaciones del agente
    sin destruir cambios preexistentes ni trabajo manual posterior del usuario.
    """
    is_git_repo: bool = False
    original_branch: str | None = None
    mission_branch: str | None = None
    base_commit: str | None = None
    # Archivos que ya tenían cambios (staged, unstaged o untracked) antes de iniciar la misión:
    # mapea ruta_relativa -> SHA-1 blob guardado en la object database de Git mediante `git hash-object -w`
    baseline_blob_oids: dict[str, str] = Field(default_factory=dict)
    # Archivos creados o modificados por agentes durante esta sesión
    agent_touched_paths: list[str] = Field(default_factory=list)
    # Archivos que NO existían ni en HEAD ni como untracked antes de la misión
    created_by_agent: list[str] = Field(default_factory=list)
    # Último SHA-256 conocido en disco tras la escritura del agente (para detectar ediciones humanas posteriores)
    expected_post_agent_hashes: dict[str, str] = Field(default_factory=dict)


class RollbackResult(BaseModel):
    status: Literal["rolled_back", "blocked", "not_git_repo", "nothing_to_revert"]
    message: str
    reverted_files: list[str] = Field(default_factory=list)
    blocked_files: list[str] = Field(default_factory=list)
    restored_branch: str | None = None


def compute_file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return "__MISSING__"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class GitSafetyManager:
    """
    Gestiona aislamiento por rama, checkpoints mediante Git Object Database
    y rollback seguro sin comandos destructivos (nunca usa `reset --hard` ni `clean -fd`).
    """

    def __init__(self, workspace_path: str | Path) -> None:
        self.ws = WorkspaceManager(workspace_path)

    def _run_git(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self.ws.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} falló: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc

    def is_git_repository(self) -> bool:
        try:
            proc = self._run_git("rev-parse", "--is-inside-work-tree")
            return proc.returncode == 0 and proc.stdout.strip().lower() == "true"
        except Exception:
            return False

    def create_checkpoint(self, session_id: str) -> GitCheckpoint:
        if not self.is_git_repository():
            return GitCheckpoint(is_git_repo=False)

        branch_proc = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        original_branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else None

        head_proc = self._run_git("rev-parse", "HEAD")
        base_commit = head_proc.stdout.strip() if head_proc.returncode == 0 else None

        # Capturar archivos sucios preexistentes (staged, unstaged y untracked)
        status_proc = self._run_git("status", "--porcelain", "-uall")
        baseline_blob_oids: dict[str, str] = {}

        if status_proc.returncode == 0:
            for raw_line in status_proc.stdout.splitlines():
                if len(raw_line) < 4:
                    continue
                rel_str = raw_line[3:].strip()
                if " -> " in rel_str:
                    rel_str = rel_str.split(" -> ", 1)[1].strip()
                rel_str = rel_str.strip('"')
                if Path(rel_str).name.lower() in BLOCKED_FILENAMES:
                    continue
                abs_file = self.ws.root / rel_str
                if abs_file.is_file():
                    oid_proc = self._run_git("hash-object", "-w", "--", rel_str)
                    if oid_proc.returncode == 0 and oid_proc.stdout.strip():
                        baseline_blob_oids[rel_str.replace("\\", "/")] = oid_proc.stdout.strip()

        # Crear rama aislada de misión conservando el working tree intacto
        short_id = session_id.replace("-", "")[:8]
        mission_branch = f"agentlab/mission-{short_id}"
        if base_commit:
            chk_proc = self._run_git("checkout", "-b", mission_branch)
            if chk_proc.returncode != 0:
                mission_branch = original_branch

        return GitCheckpoint(
            is_git_repo=True,
            original_branch=original_branch,
            mission_branch=mission_branch,
            base_commit=base_commit,
            baseline_blob_oids=baseline_blob_oids,
        )

    def record_agent_file_change(
        self,
        checkpoint: GitCheckpoint,
        rel_path: str,
        existed_before_write: bool,
    ) -> GitCheckpoint:
        norm = rel_path.replace("\\", "/")
        if norm not in checkpoint.agent_touched_paths:
            checkpoint.agent_touched_paths.append(norm)
            if not existed_before_write and norm not in checkpoint.baseline_blob_oids:
                checkpoint.created_by_agent.append(norm)

        abs_file = self.ws.root / norm
        checkpoint.expected_post_agent_hashes[norm] = compute_file_sha256(abs_file)
        return checkpoint

    def get_unified_diff(self, rel_path: str | None = None) -> str:
        if not self.is_git_repository():
            return "(El workspace actual no es un repositorio Git.)"

        path_args = ["--", rel_path] if rel_path else []
        sections: list[str] = []

        staged = self._run_git("diff", "--cached", *path_args)
        if staged.returncode == 0 and staged.stdout.strip():
            sections.append("=== STAGED CHANGES ===\n" + staged.stdout.strip())

        unstaged = self._run_git("diff", *path_args)
        if unstaged.returncode == 0 and unstaged.stdout.strip():
            sections.append("=== UNSTAGED CHANGES ===\n" + unstaged.stdout.strip())

        # Incluir archivos untracked formateados como diff nuevo
        untracked_proc = self._run_git("ls-files", "--others", "--exclude-standard", *path_args)
        if untracked_proc.returncode == 0:
            for raw_rel in untracked_proc.stdout.splitlines():
                clean_rel = raw_rel.strip()
                if not clean_rel or Path(clean_rel).name.lower() in BLOCKED_FILENAMES:
                    continue
                target = self.ws.root / clean_rel
                if not target.is_file():
                    continue
                try:
                    content_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
                    udiff = "".join(
                        difflib.unified_diff(
                            [],
                            content_lines,
                            fromfile="/dev/null",
                            tofile=f"b/{clean_rel}",
                        )
                    )
                    if udiff.strip():
                        sections.append(f"=== NEW UNTRACKED FILE: {clean_rel} ===\n" + udiff.strip())
                except Exception:
                    sections.append(f"=== NEW UNTRACKED BINARY/NON-UTF8 FILE: {clean_rel} ===")

        if not sections:
            return "(Sin cambios pendientes en Git.)"

        combined = "\n\n".join(sections)
        if len(combined) > MAX_DIFF_CHARS:
            return combined[:MAX_DIFF_CHARS] + "\n... [Diff truncado por longitud]"
        return combined

    def get_status_summary(self) -> str:
        if not self.is_git_repository():
            return "(El workspace actual no es un repositorio Git.)"
        branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        status = self._run_git("status", "--short").stdout.strip()
        return f"Rama actual: {branch}\n{status or '(Árbol de trabajo limpio)'}"

    def rollback_mission(self, checkpoint: GitCheckpoint) -> RollbackResult:
        if not checkpoint.is_git_repo or not self.is_git_repository():
            return RollbackResult(
                status="not_git_repo",
                message="El workspace no es un repositorio Git; no hay checkpoint Git para revertir.",
            )

        if not checkpoint.agent_touched_paths:
            return RollbackResult(
                status="nothing_to_revert",
                message="Los agentes no modificaron ni crearon archivos en esta misión.",
            )

        # 1. Preflight check: bloquear si algún archivo fue modificado manualmente tras el agente
        blocked: list[str] = []
        for rel_path in checkpoint.agent_touched_paths:
            expected_hash = checkpoint.expected_post_agent_hashes.get(rel_path)
            if expected_hash:
                current_hash = compute_file_sha256(self.ws.root / rel_path)
                if current_hash != expected_hash:
                    blocked.append(rel_path)

        if blocked:
            return RollbackResult(
                status="blocked",
                message=(
                    "Rollback bloqueado para proteger modificaciones manuales posteriores del usuario en: "
                    + ", ".join(blocked)
                ),
                blocked_files=blocked,
            )

        # 2. Restauración selectiva y no destructiva por archivo
        reverted: list[str] = []
        for rel_path in checkpoint.agent_touched_paths:
            abs_file = self.ws.root / rel_path
            if rel_path in checkpoint.baseline_blob_oids:
                # Restaurar exactamente el contenido sucio que el usuario tenía antes de la misión
                blob_oid = checkpoint.baseline_blob_oids[rel_path]
                blob_proc = subprocess.run(
                    ["git", "cat-file", "blob", blob_oid],
                    cwd=str(self.ws.root),
                    capture_output=True,
                    timeout=10,
                )
                if blob_proc.returncode == 0:
                    abs_file.parent.mkdir(parents=True, exist_ok=True)
                    abs_file.write_bytes(blob_proc.stdout)
                    reverted.append(rel_path)
            elif rel_path in checkpoint.created_by_agent:
                # Eliminar solo el archivo nuevo creado por el agente
                if abs_file.exists() and abs_file.is_file():
                    abs_file.unlink()
                    reverted.append(rel_path)
            else:
                # Restaurar archivo rastreado limpio desde HEAD
                chk = self._run_git("checkout", "HEAD", "--", rel_path)
                if chk.returncode == 0:
                    reverted.append(rel_path)

        # 3. Volver a la rama original si la misión creó una rama dedicada y no quedan otros cambios
        restored_branch = None
        if (
            checkpoint.original_branch
            and checkpoint.mission_branch
            and checkpoint.original_branch != checkpoint.mission_branch
        ):
            sw = self._run_git("checkout", checkpoint.original_branch)
            if sw.returncode == 0:
                restored_branch = checkpoint.original_branch

        return RollbackResult(
            status="rolled_back",
            message=f"Rollback seguro completado sobre {len(reverted)} archivo(s) sin afectar trabajo previo.",
            reverted_files=reverted,
            restored_branch=restored_branch,
        )


class GitStatusArgs(BaseModel):
    pass


class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Muestra la rama Git actual y el estado de archivos modificados, staged o untracked."
    risk_level: RiskLevel = "safe"
    args_schema = GitStatusArgs

    async def execute(self, tool_call_id: str, args: BaseModel, workspace_path: Path) -> ToolResult:
        start = time.perf_counter()
        mgr = GitSafetyManager(workspace_path)
        out = await asyncio.to_thread(mgr.get_status_summary)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status="success",
            output=out,
            execution_time_ms=elapsed_ms,
        )


class GitDiffArgs(BaseModel):
    path: str = Field(
        default="",
        description="Ruta relativa opcional de un archivo específico para ver su diff (vacío = todos los cambios).",
    )


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "Obtiene el diff unificado de cambios staged, unstaged y archivos nuevos untracked en el repositorio."
    risk_level: RiskLevel = "safe"
    args_schema = GitDiffArgs

    async def execute(self, tool_call_id: str, args: BaseModel, workspace_path: Path) -> ToolResult:
        start = time.perf_counter()
        parsed = GitDiffArgs.model_validate(args)
        mgr = GitSafetyManager(workspace_path)
        out = await asyncio.to_thread(mgr.get_unified_diff, parsed.path.strip() or None)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status="success",
            output=out,
            execution_time_ms=elapsed_ms,
        )
def build_hitl_file_preview(
    workspace_path: Path,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[str | None, str | None]:
    """
    Simula en memoria el cambio de `write_file` o `edit_file` sin tocar el disco,
    devolviendo `(diff_preview, target_file_sha256)` para validación de integridad al aprobar.
    """
    if tool_name not in ("write_file", "edit_file"):
        return None, None

    raw_path = str(arguments.get("path", "")).strip()
    if not raw_path:
        return None, None

    try:
        ws = WorkspaceManager(workspace_path)
        target = ws.resolve_path(raw_path)
        rel_posix = ws.to_relative_posix(target)
    except Exception:
        return None, None

    current_sha = compute_file_sha256(target)
    existed = target.exists() and target.is_file()
    old_text = target.read_text(encoding="utf-8", errors="replace") if existed else ""

    if tool_name == "write_file":
        new_text = str(arguments.get("content", ""))
    else:
        search_block = str(arguments.get("old_text", ""))
        replace_block = str(arguments.get("new_text", ""))
        if not existed or search_block not in old_text:
            new_text = old_text
        else:
            new_text = old_text.replace(search_block, replace_block, 1)

    old_lines = old_text.splitlines(keepends=True) if existed else []
    new_lines = new_text.splitlines(keepends=True)
    from_file = f"a/{rel_posix}" if existed else "/dev/null"
    to_file = f"b/{rel_posix}"

    udiff = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_file,
            tofile=to_file,
        )
    )
    if not udiff.strip():
        udiff = f"(Sin diferencias textuales respecto al contenido actual de {rel_posix})"
    elif len(udiff) > MAX_DIFF_CHARS:
        udiff = udiff[:MAX_DIFF_CHARS] + "\n... [Vista previa truncada por longitud]"

    return udiff, current_sha