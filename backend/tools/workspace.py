import shutil
from datetime import datetime, timezone
from pathlib import Path

BLOCKED_FILENAMES = {".env", "id_rsa", "id_ed25519"}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
INTERNAL_META_DIR = ".agentlab"


class WorkspaceManager:
    """
    Gestiona el aislamiento de rutas, protección de secretos y copias de seguridad
    antes de mutaciones dentro del workspace de una sesión.
    """

    def __init__(self, workspace_path: str | Path) -> None:
        self.root = Path(workspace_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, relative_path: str, *, allow_internal: bool = False) -> Path:
        """
        Resuelve una ruta relativa dentro del workspace y bloquea escapes (path traversal)
        o acceso a archivos sensibles.
        """
        target = (self.root / relative_path).resolve()

        if not target.is_relative_to(self.root):
            raise PermissionError(
                f"Acceso denegado: '{relative_path}' intenta salir del workspace permitido."
            )

        rel_parts = target.relative_to(self.root).parts
        if not allow_internal and INTERNAL_META_DIR in rel_parts:
            raise PermissionError(
                f"Acceso denegado: '{relative_path}' apunta al directorio interno '{INTERNAL_META_DIR}'."
            )

        name_lower = target.name.lower()
        if (
            name_lower in BLOCKED_FILENAMES
            or name_lower.startswith(".env.")
            or target.suffix.lower() in BLOCKED_SUFFIXES
            or ".git" in rel_parts
        ):
            raise PermissionError(
                f"Acceso denegado por política de seguridad al archivo sensible '{relative_path}'."
            )

        return target

    def to_relative_posix(self, target: Path) -> str:
        return target.resolve().relative_to(self.root).as_posix()

    def create_backup(self, target: Path) -> Path | None:
        """
        Si el archivo objetivo ya existe, guarda un respaldo con timestamp UTC en
        .agentlab/backups/ antes de sobrescribirlo o editarlo.
        """
        if not target.exists() or not target.is_file():
            return None

        rel_path = target.relative_to(self.root)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = self.root / INTERNAL_META_DIR / "backups" / rel_path.parent
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_file = backup_dir / f"{target.name}.{timestamp}.bak"
        shutil.copy2(target, backup_file)
        return backup_file
