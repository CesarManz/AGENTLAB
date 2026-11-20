import asyncio
from pathlib import Path

from backend.tools.knowledge_graph import ASTKnowledgeGraph, QueryCodeGraphArgs, QueryCodeGraphTool


def test_ast_knowledge_graph_indexes_classes_methods_and_filters_queries(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "models.py").write_text(
        '''
from dataclasses import dataclass

@dataclass
class UserAccount:
    """Representa una cuenta de usuario."""
    username: str

    def is_admin(self) -> bool:
        return self.username == "admin"
''',
        encoding="utf-8",
    )
    (ws / "math_ops.py").write_text(
        '''
def calcular_iva(monto: float, tasa: float = 0.19) -> float:
    return round(monto * tasa, 2)
''',
        encoding="utf-8",
    )

    graph = ASTKnowledgeGraph(ws)
    modules = graph.index_workspace()
    assert len(modules) == 2

    full_map = graph.render_compact_map()
    assert "FILE: models.py" in full_map
    assert "class UserAccount" in full_map
    assert "def is_admin(self) -> bool" in full_map
    assert "def calcular_iva(monto: float, tasa: float) -> float" in full_map

    # Filtro puntual por símbolo
    tool = QueryCodeGraphTool()
    res = asyncio.run(
        tool.execute(
            tool_call_id="call_kg_1",
            args=QueryCodeGraphArgs(query="calcular_iva"),
            workspace_path=ws,
        )
    )
    assert res.status == "success"
    assert "math_ops.py" in res.output
    assert "models.py" not in res.output