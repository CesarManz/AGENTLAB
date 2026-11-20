from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    name: str
    triggers: tuple[str, ...]
    instructions: str
    source_path: str


class SkillRegistry:
    """
    Carga habilidades modulares desde archivos Markdown (skills/*.md)
    y selecciona dinámicamente las relevantes según default_skills y la tarea.
    """

    def __init__(self, skills_dir: str | Path = "skills") -> None:
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, SkillDefinition] = {}

    def load_from_directory(self) -> int:
        self._skills.clear()
        if not self.skills_dir.exists():
            return 0

        for md_file in sorted(self.skills_dir.glob("*.md")):
            parsed = self._parse_markdown_skill(md_file)
            if parsed is not None:
                self._skills[parsed.id] = parsed
        return len(self._skills)

    def _parse_markdown_skill(self, path: Path) -> SkillDefinition | None:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None

        skill_id = path.stem
        skill_name = path.stem.replace("_", " ").title()
        triggers: list[str] = []
        body = raw

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) == 3:
                header_lines = parts[1].strip().splitlines()
                body = parts[2].strip()
                for line in header_lines:
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    k = key.strip().lower()
                    v = val.strip()
                    if k == "id" and v:
                        skill_id = v
                    elif k == "name" and v:
                        skill_name = v
                    elif k == "triggers" and v:
                        triggers = [t.strip().lower() for t in v.split(",") if t.strip()]

        return SkillDefinition(
            id=skill_id,
            name=skill_name,
            triggers=tuple(triggers),
            instructions=body,
            source_path=str(path),
        )

    def list_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def resolve_for_task(
        self,
        *,
        task_instruction: str,
        default_skills: tuple[str, ...] = (),
    ) -> list[SkillDefinition]:
        selected: dict[str, SkillDefinition] = {}

        for sid in default_skills:
            skill = self._skills.get(sid)
            if skill is not None:
                selected[skill.id] = skill

        lowered_task = task_instruction.lower()
        for skill in self._skills.values():
            if skill.id in selected:
                continue
            if any(trigger in lowered_task for trigger in skill.triggers):
                selected[skill.id] = skill

        return list(selected.values())

    def render_prompt_block(self, skills: list[SkillDefinition]) -> str:
        if not skills:
            return ""
        sections = [
            f"### SKILL ACTIVA: {s.name} (`{s.id}`)\n{s.instructions}"
            for s in skills
        ]
        return "\n\n---\n## GUÍAS Y SKILLS ACTIVAS PARA ESTA MISIÓN\n\n" + "\n\n".join(sections)