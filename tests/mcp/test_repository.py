import subprocess
from pathlib import Path

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.repository import RepositoryMCP
from engineering_team.workspace.isolation import create_run_copy


def test_repository_mcp_reads_and_writes_only_inside_run_workspace(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    mcp = RepositoryMCP(tmp_path)

    assert "file.txt" in mcp.list_files(AgentRole.DEVELOPER).output_summary
    assert mcp.read_file(AgentRole.ARCHITECTURE, "file.txt").status is ToolStatus.SUCCESS
    assert mcp.create_file(AgentRole.DEVELOPER, "new.txt", "safe").status is ToolStatus.SUCCESS


def test_repository_mcp_denies_path_traversal_and_architecture_writes(tmp_path: Path) -> None:
    mcp = RepositoryMCP(tmp_path)
    assert mcp.read_file(AgentRole.DEVELOPER, "../outside.txt").status is ToolStatus.DENIED
    assert mcp.create_file(AgentRole.ARCHITECTURE, "x.txt", "x").status is ToolStatus.DENIED


def test_each_run_uses_an_isolated_source_copy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("safe = True", encoding="utf-8")

    run = create_run_copy("run-123", source, tmp_path / "runs")
    RepositoryMCP(run).update_file(AgentRole.DEVELOPER, "app.py", "safe = False")

    assert (source / "app.py").read_text(encoding="utf-8") == "safe = True"
    assert (run / "app.py").read_text(encoding="utf-8") == "safe = False"


def test_search_code_never_reads_secret_paths_but_keeps_allowed_matches(tmp_path: Path) -> None:
    sentinel = "FICTIONAL_REPOSITORY_SENTINEL_77"
    (tmp_path / ".env").write_text(sentinel, encoding="utf-8")
    (tmp_path / ".env.audit").write_text(sentinel, encoding="utf-8")
    (tmp_path / "allowed.py").write_text(sentinel, encoding="utf-8")
    mcp = RepositoryMCP(tmp_path)

    result = mcp.search_code(AgentRole.DEVELOPER, sentinel)

    assert result.status is ToolStatus.SUCCESS
    assert result.output_summary.splitlines() == ["allowed.py"]
    assert sentinel not in result.output_summary


def _git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text("ignored/\n*.log\n", encoding="utf-8")


def test_list_files_respects_git_exclusions(tmp_path: Path) -> None:
    """Finding 4: _safe_files recorria el arbol entero. En este checkout eso son
    114.875 rutas y 11 MB en un solo output_summary."""
    _git_repo(tmp_path)
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "huge.bin").write_text("x", encoding="utf-8")
    (tmp_path / "debug.log").write_text("noise", encoding="utf-8")

    listed = RepositoryMCP(tmp_path).list_files(AgentRole.ARCHITECTURE).output_summary

    assert "app.py" in listed
    assert "ignored" not in listed, "una ruta ignorada por git llego al listado"
    assert "debug.log" not in listed


def test_list_files_never_exposes_the_git_directory(tmp_path: Path) -> None:
    """.git/config puede llevar credenciales en las URLs de los remotos."""
    _git_repo(tmp_path)
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")

    listed = RepositoryMCP(tmp_path).list_files(AgentRole.ARCHITECTURE).output_summary

    assert ".git/" not in listed
    assert "config" not in listed.replace("app.py", "")


def test_list_files_excludes_heavy_directories_without_git(tmp_path: Path) -> None:
    """Sin repo git no hay exclusiones que consultar, pero los directorios
    pesados conocidos no son evidencia arquitectonica en ningun caso."""
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    for noisy in ("node_modules", ".venv", "__pycache__"):
        (tmp_path / noisy).mkdir()
        (tmp_path / noisy / "junk.py").write_text("x", encoding="utf-8")

    listed = RepositoryMCP(tmp_path).list_files(AgentRole.ARCHITECTURE).output_summary

    assert "app.py" in listed
    for noisy in ("node_modules", ".venv", "__pycache__"):
        assert noisy not in listed


def test_list_files_is_bounded_and_marks_truncation(tmp_path: Path) -> None:
    """El listado entra a estado y trazas: no puede crecer con el proyecto."""
    for index in range(5_000):
        (tmp_path / f"file_{index}.py").write_text("x", encoding="utf-8")

    result = RepositoryMCP(tmp_path).list_files(AgentRole.ARCHITECTURE)

    assert result.status is ToolStatus.SUCCESS
    assert len(result.output_summary.encode()) <= 256 * 1024
    assert "truncated" in result.output_summary.lower()

