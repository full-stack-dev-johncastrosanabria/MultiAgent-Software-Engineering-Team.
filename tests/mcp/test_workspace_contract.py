"""The two places a project's files can live, held to the same contract.

ADR 17. The host implementation is exercised directly; the volume one is
exercised against a real daemon when an image is available, and its argv is
asserted without one -- the properties that matter without a daemon are which
mounts it asks for, that it never passes a token on the command line, and that
it refuses to leave the project root.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.repository import RepositoryMCP
from engineering_team.workspace.contract import (
    PROJECT_MOUNT,
    HostWorkspace,
    VolumeWorkspace,
    Workspace,
    WorkspaceError,
    refuse_traversal,
)

PINNED = "python@sha256:" + "0" * 64
LIVE_IMAGE = os.environ.get("ASET_WORKSPACE_TEST_IMAGE", "")


def _volume(name: str = "aset-test-workspace", **kwargs) -> VolumeWorkspace:
    return VolumeWorkspace(name, image=PINNED, run_id="apply-1", project="demo", **kwargs)


def test_both_implementations_satisfy_the_contract(tmp_path: Path) -> None:
    assert isinstance(HostWorkspace(tmp_path), Workspace)
    assert isinstance(_volume(), Workspace)


@pytest.mark.parametrize("relative", ["../escape", "/etc/passwd", ".env", "app/.env.local"])
def test_no_implementation_leaves_the_project_or_reads_a_secret(relative: str) -> None:
    with pytest.raises(ValueError):
        refuse_traversal(relative)


def test_the_host_workspace_reads_writes_lists_and_searches(tmp_path: Path) -> None:
    workspace = HostWorkspace(tmp_path)
    workspace.write("api/app.py", "value = 1\n")
    assert workspace.read("api/app.py") == "value = 1\n"
    assert workspace.exists("api/app.py")
    assert Path("api/app.py") in workspace.list_paths()
    assert workspace.search("value") == [Path("api/app.py")]
    assert not workspace.exists("api/missing.py")


def test_the_host_workspace_hides_what_the_project_declares_disposable(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "index.js").write_text("noise")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "app.py").write_text("kept")
    listed = HostWorkspace(tmp_path).list_paths()
    assert listed == [Path("app.py")]


def test_the_repository_tool_works_through_an_injected_workspace(tmp_path: Path) -> None:
    """The point of the extraction: policy stays, the filesystem is replaceable."""
    workspace = HostWorkspace(tmp_path)
    repository = RepositoryMCP(workspace=workspace)
    assert repository.root == tmp_path.resolve()
    created = repository.create_file(AgentRole.DEVELOPER, "app.py", "x = 1")
    assert created.status is ToolStatus.SUCCESS
    assert workspace.read("app.py") == "x = 1\n"
    diff = repository.get_diff(AgentRole.DEVELOPER)
    assert "+x = 1" in diff.output_summary


def test_a_repository_without_a_root_or_a_workspace_is_refused() -> None:
    with pytest.raises(ValueError):
        RepositoryMCP()


def test_the_volume_workspace_mounts_only_the_project_and_no_network() -> None:
    workspace = _volume()
    argv = []
    workspace._runtime_call = lambda arguments, **kwargs: argv.extend(arguments) or (
        subprocess.CompletedProcess(arguments, 0, "", "")
    )
    workspace.exists("app.py")
    assert f"type=volume,source=aset-test-workspace,target={PROJECT_MOUNT}" in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert not any(item.startswith("type=bind") for item in argv)
    assert "aset.run=apply-1" in argv and "aset.project=demo" in argv


def test_the_clone_token_never_reaches_the_command_line() -> None:
    workspace = _volume()
    seen: dict = {}

    def _call(arguments, **kwargs):
        seen["argv"] = arguments
        seen["env"] = kwargs.get("environment") or {}
        return subprocess.CompletedProcess(arguments, 0, "", "")

    workspace._runtime_call = _call
    workspace.clone("https://github.com/owner/repo.git", token="ghp_secret")
    assert not any("ghp_secret" in item for item in seen["argv"])
    assert seen["env"]["ASET_CLONE_TOKEN"] == "ghp_secret"
    assert "--env" in seen["argv"]
    # Shallow on purpose (ADR 17): history is traded for bandwidth, by name.
    assert "--depth" in " ".join(seen["argv"]) and "1" in " ".join(seen["argv"])


def test_a_clone_without_a_token_asks_for_no_environment() -> None:
    workspace = _volume()
    seen: dict = {}
    workspace._runtime_call = lambda arguments, **kwargs: (
        seen.update(argv=arguments) or subprocess.CompletedProcess(arguments, 0, "", "")
    )
    workspace.clone("https://github.com/owner/public.git")
    assert "--env" not in seen["argv"]


def test_a_runtime_that_refuses_is_reported_not_swallowed() -> None:
    workspace = _volume()
    workspace._runtime_call = lambda arguments, **kwargs: subprocess.CompletedProcess(
        arguments, 1, "", "no such volume"
    )
    with pytest.raises(WorkspaceError):
        workspace.up()
    with pytest.raises(WorkspaceError):
        workspace.read("app.py")


@pytest.mark.skipif(
    not LIVE_IMAGE or shutil.which("docker") is None,
    reason="set ASET_WORKSPACE_TEST_IMAGE to a locally present image",
)
def test_a_real_volume_round_trips_a_file_and_dies_with_the_run(tmp_path: Path) -> None:
    source = tmp_path / "project"
    (source / "api").mkdir(parents=True)
    (source / "api" / "app.py").write_text("value = 1\n")
    name = "aset-test-workspace-live"
    with VolumeWorkspace(name, image=LIVE_IMAGE, run_id="apply-live", project="demo") as workspace:
        workspace.populate_from_host(source)
        assert workspace.read("api/app.py") == "value = 1\n"
        workspace.write("api/app.py", "value = 2\n")
        assert workspace.read("api/app.py") == "value = 2\n"
        assert Path("api/app.py") in workspace.list_paths()
        assert workspace.search("value = 2") == [Path("api/app.py")]
    listed = subprocess.run(
        ["docker", "volume", "ls", "--quiet", "--filter", f"name={name}"],
        capture_output=True, text=True, check=False,
    )
    assert name not in listed.stdout


def test_evidence_is_extracted_by_name_and_nothing_else(tmp_path: Path) -> None:
    """ADR 17: teardown that kept nothing would be worse than the host copy."""
    workspace = _volume()
    workspace._in_container = lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, "diff body", ""
    )
    written = workspace.extract(tmp_path / "evidence", "reports/diff.patch")
    assert written == [Path("reports/diff.patch")]
    assert (tmp_path / "evidence" / "reports" / "diff.patch").read_text() == "diff body"
    # Nothing arrives that was not asked for.
    assert list((tmp_path / "evidence").rglob("*.py")) == []


def test_extraction_refuses_to_reach_outside_the_project(tmp_path: Path) -> None:
    workspace = _volume()
    workspace._in_container = lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, "", ""
    )
    with pytest.raises(ValueError):
        workspace.extract(tmp_path, "../../etc/passwd")


def test_a_file_the_volume_does_not_hold_is_skipped_not_invented(tmp_path: Path) -> None:
    workspace = _volume()
    workspace._in_container = lambda command, **kwargs: subprocess.CompletedProcess(
        command, 1, "", "no such file"
    )
    assert workspace.extract(tmp_path, "missing.txt") == []
