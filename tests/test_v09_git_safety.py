import asyncio
import subprocess
from pathlib import Path

from backend.tools.git_ops import GitDiffArgs, GitDiffTool, GitSafetyManager, GitStatusArgs, GitStatusTool


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@agentlab.local"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.name", "AgentLab Test"], cwd=str(repo_dir), check=True)
    (repo_dir / "app.py").write_text("def saludar():\n    return 'hola'\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo_dir), check=True, capture_output=True)


def test_git_checkpoint_isolates_branch_and_preserves_user_dirty_changes_on_same_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    # El usuario ya tiene cambios sin commitear en app.py ANTES de lanzar la misión
    user_dirty_content = "def saludar():\n    return 'hola mundo usuario'\n"
    (repo / "app.py").write_text(user_dirty_content, encoding="utf-8")

    mgr = GitSafetyManager(repo)
    cp = mgr.create_checkpoint("12345678-aaaa-bbbb-cccc-1234567890ab")

    assert cp.is_git_repo is True
    assert cp.mission_branch == "agentlab/mission-12345678"
    assert "app.py" in cp.baseline_blob_oids

    # El agente modifica el MISMO archivo app.py y además crea nuevo.py
    (repo / "app.py").write_text("def saludar():\n    return 'cambio del agente'\n", encoding="utf-8")
    cp = mgr.record_agent_file_change(cp, "app.py", existed_before_write=True)

    (repo / "nuevo.py").write_text("X = 42\n", encoding="utf-8")
    cp = mgr.record_agent_file_change(cp, "nuevo.py", existed_before_write=False)

    # Verificar que git_diff incluye modificados y untracked
    diff_tool = GitDiffTool()
    diff_res = asyncio.run(diff_tool.execute("c1", GitDiffArgs(), repo))
    assert diff_res.status == "success"
    assert "cambio del agente" in diff_res.output
    assert "NEW UNTRACKED FILE: nuevo.py" in diff_res.output

    # Rollback seguro: restaura app.py al estado sucio exacto del usuario y elimina nuevo.py
    rb = mgr.rollback_mission(cp)
    assert rb.status == "rolled_back"
    assert (repo / "app.py").read_text(encoding="utf-8") == user_dirty_content
    assert not (repo / "nuevo.py").exists()
    assert rb.restored_branch == cp.original_branch


def test_git_rollback_blocks_when_user_edited_file_after_agent(tmp_path: Path) -> None:
    repo = tmp_path / "repo_conflict"
    repo.mkdir()
    _init_git_repo(repo)

    mgr = GitSafetyManager(repo)
    cp = mgr.create_checkpoint("abcdef12-0000-0000-0000-000000000000")

    # Agente edita app.py
    (repo / "app.py").write_text("def saludar():\n    return 'agente'\n", encoding="utf-8")
    cp = mgr.record_agent_file_change(cp, "app.py", existed_before_write=True)

    # Usuario edita manualmente app.py DESPUÉS del agente
    manual_edit = "def saludar():\n    return 'edicion manual posterior'\n"
    (repo / "app.py").write_text(manual_edit, encoding="utf-8")

    rb = mgr.rollback_mission(cp)
    assert rb.status == "blocked"
    assert "app.py" in rb.blocked_files
    # El trabajo manual del usuario permanece intacto
    assert (repo / "app.py").read_text(encoding="utf-8") == manual_edit


def test_git_safety_degrades_gracefully_outside_git_repo(tmp_path: Path) -> None:
    plain_dir = tmp_path / "no_git"
    plain_dir.mkdir()

    mgr = GitSafetyManager(plain_dir)
    cp = mgr.create_checkpoint("99999999-1111-2222-3333-444444444444")
    assert cp.is_git_repo is False

    status_tool = GitStatusTool()
    st = asyncio.run(status_tool.execute("c2", GitStatusArgs(), plain_dir))
    assert st.status == "success"
    assert "no es un repositorio Git" in st.output