import ast
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from backend.tools.base import BaseTool
from backend.tools.filesystem import IGNORED_DIRS
from backend.tools.schemas import RiskLevel, ToolResult
from backend.tools.workspace import BLOCKED_FILENAMES, WorkspaceManager


@dataclass
class FunctionSymbol:
    name: str
    signature: str
    lineno: int
    is_async: bool = False
    docstring: str | None = None


@dataclass
class ClassSymbol:
    name: str
    bases: list[str]
    lineno: int
    methods: list[FunctionSymbol] = field(default_factory=list)
    docstring: str | None = None


@dataclass
class ModuleNode:
    rel_path: str
    imports: list[str] = field(default_factory=list)
    classes: list[ClassSymbol] = field(default_factory=list)
    functions: list[FunctionSymbol] = field(default_factory=list)
    parse_error: str | None = None


def _format_arg(arg: ast.arg) -> str:
    if arg.annotation is None:
        return arg.arg
    try:
        return f"{arg.arg}: {ast.unparse(arg.annotation)}"
    except Exception:
        return arg.arg


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [_format_arg(a) for a in node.args.args]
    if node.args.vararg:
        args.append(f"*{_format_arg(node.args.vararg)}")
    for a in node.args.kwonlyargs:
        args.append(_format_arg(a))
    if node.args.kwarg:
        args.append(f"**{_format_arg(node.args.kwarg)}")

    ret = ""
    if node.returns is not None:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            ret = ""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{prefix}{node.name}({', '.join(args)}){ret}"


def _short_doc(node: ast.AST) -> str | None:
    raw = ast.get_docstring(node, clean=True)
    if not raw:
        return None
    first_line = raw.splitlines()[0].strip()
    return first_line[:110]


class ASTKnowledgeGraph:
    """
    Construye un grafo estructural en memoria de los archivos Python de un workspace
    mediante análisis estático AST (sin gastar tokens LLM).
    """

    def __init__(self, workspace_path: str | Path) -> None:
        self.ws = WorkspaceManager(workspace_path)
        self.modules: list[ModuleNode] = []

    def index_workspace(self) -> list[ModuleNode]:
        self.modules.clear()
        for py_file in sorted(self.ws.root.rglob("*.py")):
            if not py_file.is_file():
                continue
            rel_parts = py_file.relative_to(self.ws.root).parts
            if any(part in IGNORED_DIRS for part in rel_parts):
                continue
            if py_file.name.lower() in BLOCKED_FILENAMES:
                continue

            rel_path = self.ws.to_relative_posix(py_file)
            self.modules.append(self._parse_file(py_file, rel_path))
        return self.modules

    def _parse_file(self, file_path: Path, rel_path: str) -> ModuleNode:
        mod = ModuleNode(rel_path=rel_path)
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel_path)
        except Exception as exc:
            mod.parse_error = f"{type(exc).__name__}: {exc}"
            return mod

        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    mod.imports.append(alias.name)
            elif isinstance(stmt, ast.ImportFrom):
                base = stmt.module or ""
                names = ", ".join(a.name for a in stmt.names)
                mod.imports.append(f"{base} ({names})" if base else names)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mod.functions.append(
                    FunctionSymbol(
                        name=stmt.name,
                        signature=_format_signature(stmt),
                        lineno=stmt.lineno,
                        is_async=isinstance(stmt, ast.AsyncFunctionDef),
                        docstring=_short_doc(stmt),
                    )
                )
            elif isinstance(stmt, ast.ClassDef):
                bases: list[str] = []
                for b in stmt.bases:
                    try:
                        bases.append(ast.unparse(b))
                    except Exception:
                        pass
                cls_sym = ClassSymbol(
                    name=stmt.name,
                    bases=bases,
                    lineno=stmt.lineno,
                    docstring=_short_doc(stmt),
                )
                for item in stmt.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        cls_sym.methods.append(
                            FunctionSymbol(
                                name=item.name,
                                signature=_format_signature(item),
                                lineno=item.lineno,
                                is_async=isinstance(item, ast.AsyncFunctionDef),
                                docstring=_short_doc(item),
                            )
                        )
                mod.classes.append(cls_sym)

        return mod

    def render_compact_map(self, query: str | None = None, max_modules: int = 25) -> str:
        if not self.modules:
            self.index_workspace()

        if not self.modules:
            return "(No se encontraron archivos .py indexables en el workspace.)"

        q = (query or "").strip().lower()
        lines: list[str] = []
        matched_modules = 0

        for mod in self.modules:
            if matched_modules >= max_modules:
                break

            mod_matches = not q or q in mod.rel_path.lower()
            matching_classes = [
                c for c in mod.classes
                if mod_matches
                or q in c.name.lower()
                or any(q in m.name.lower() for m in c.methods)
            ]
            matching_funcs = [
                f for f in mod.functions
                if mod_matches or q in f.name.lower()
            ]

            if not mod_matches and not matching_classes and not matching_funcs:
                continue

            matched_modules += 1
            lines.append(f"FILE: {mod.rel_path}")
            if mod.parse_error:
                lines.append(f"  [SyntaxError] {mod.parse_error}")
                continue
            if mod.imports:
                lines.append(f"  imports: {', '.join(mod.imports[:10])}")

            for cls in (mod.classes if mod_matches else matching_classes):
                base_str = f"({', '.join(cls.bases)})" if cls.bases else ""
                lines.append(f"  class {cls.name}{base_str} [L{cls.lineno}]")
                for m in cls.methods:
                    lines.append(f"    - {m.signature} [L{m.lineno}]")

            for fn in (mod.functions if mod_matches else matching_funcs):
                lines.append(f"  - {fn.signature} [L{fn.lineno}]")

        if not lines:
            return f"No se encontraron símbolos ni módulos que coincidan con '{query}'."

        header = f"AST KNOWLEDGE GRAPH ({matched_modules} módulos Python indexados):\n"
        return header + "\n".join(lines)


class QueryCodeGraphArgs(BaseModel):
    query: str = Field(
        default="",
        description="Filtro opcional por nombre de archivo, clase o función (vacío = mapa completo del repo).",
    )


class QueryCodeGraphTool(BaseTool):
    name = "query_code_graph"
    description = (
        "Consulta el grafo estructural AST del código Python del workspace "
        "(clases, métodos, firmas tipadas, líneas e imports) sin leer archivos completos."
    )
    risk_level: RiskLevel = "safe"
    args_schema = QueryCodeGraphArgs

    async def execute(
        self,
        tool_call_id: str,
        args: BaseModel,
        workspace_path: Path,
    ) -> ToolResult:
        start = time.perf_counter()
        parsed = QueryCodeGraphArgs.model_validate(args)
        graph = ASTKnowledgeGraph(workspace_path)
        graph.index_workspace()
        rendered = graph.render_compact_map(query=parsed.query)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status="success",
            output=rendered,
            execution_time_ms=elapsed_ms,
            metadata={"indexed_modules": len(graph.modules)},
        )