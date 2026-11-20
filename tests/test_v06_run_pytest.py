import asyncio
from pathlib import Path

from backend.tools.execution import RunPytestArgs, RunPytestTool


def test_run_pytest_passes_valid_suite(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "calc.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (ws / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    tool = RunPytestTool()
    assert tool.risk_level == "critical"

    res = asyncio.run(tool.execute("tc_1", RunPytestArgs(target_path="test_calc.py"), ws))
    assert res.status == "success"
    assert "1 passed" in res.output


def test_run_pytest_reports_failing_test(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "test_fail.py").write_text(
        "def test_broken():\n    assert 1 + 1 == 3\n",
        encoding="utf-8",
    )

    tool = RunPytestTool()
    res = asyncio.run(tool.execute("tc_2", RunPytestArgs(target_path="."), ws))
    assert res.status == "error"
    assert "[EXIT CODE 1]" in res.output
    assert "1 failed" in res.output


def test_run_pytest_blocks_path_traversal(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    tool = RunPytestTool()
    res = asyncio.run(tool.execute("tc_3", RunPytestArgs(target_path="../"), ws))
    assert res.status == "error"
    assert "Acceso denegado" in res.output


def test_run_pytest_enforces_timeout(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "test_hang.py").write_text(
        "import time\n\ndef test_infinite():\n    time.sleep(5)\n",
        encoding="utf-8",
    )

    tool = RunPytestTool()
    tool.timeout_seconds = 1
    res = asyncio.run(tool.execute("tc_4", RunPytestArgs(target_path="test_hang.py"), ws))
    assert res.status == "timeout"
    assert "Timeout" in res.output
