"""What the container runner asks the runtime for, and what it refuses to.

Most of these read the argv rather than start a container: the security
properties live in the flags, and asserting them does not need a daemon. The
tests that do need one are gated on an image already being present locally.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from engineering_team.mcp.container import (
    ENVIRONMENT_MOUNT,
    WORKSPACE_MOUNT,
    ContainerLimits,
    ContainerRunner,
)
from engineering_team.mcp.runner import CommandRequest, CommandRunner

PINNED = "python@sha256:" + "0" * 64
INTEGRATION_IMAGE = os.environ.get("ASET_CONTAINER_TEST_IMAGE", "")


def _runner(workspace: Path, **kwargs) -> ContainerRunner:
    return ContainerRunner(workspace, image=PINNED, **kwargs)


def _request(cwd: Path, *args: str, **kwargs) -> CommandRequest:
    return CommandRequest(
        args=args, cwd=cwd, deadline=time.monotonic() + 60, **kwargs
    )


def test_container_runner_satisfies_the_interface(tmp_path: Path) -> None:
    assert isinstance(_runner(tmp_path), CommandRunner)


def test_image_must_be_pinned_by_digest(tmp_path: Path) -> None:
    """An unpinned tag is a different image tomorrow."""
    with pytest.raises(ValueError, match="pinned by digest"):
        ContainerRunner(tmp_path, image="python:3.13-slim")
    with pytest.raises(ValueError, match="pinned by digest"):
        ContainerRunner(tmp_path, image="python@sha256:tooshort")
    # The escape hatch is explicit and has to be asked for by name.
    ContainerRunner(tmp_path, image="python:3.13-slim", allow_unpinned_image=True)


def test_offline_by_default_and_networked_only_when_asked(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    offline = runner._container_command("c1", _request(tmp_path, "true"))
    assert offline[offline.index("--network") + 1] == "none"
    installing = runner._container_command(
        "c2", _request(tmp_path, "pip", "install", "x", allow_network=True)
    )
    assert installing[installing.index("--network") + 1] == "bridge"


def test_privileges_are_dropped_and_cannot_be_regained(tmp_path: Path) -> None:
    command = _runner(tmp_path)._container_command("c1", _request(tmp_path, "true"))
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"


def test_only_the_workspace_and_the_environment_are_mounted(tmp_path: Path) -> None:
    """Nothing else on the host is reachable from inside."""
    runner = _runner(tmp_path)
    command = runner._container_command("c1", _request(tmp_path, "true"))
    mounts = [command[i + 1] for i, a in enumerate(command) if a == "--mount"]
    assert len(mounts) == 2
    assert f"type=bind,source={tmp_path},target={WORKSPACE_MOUNT}" in mounts
    assert any(
        m.startswith("type=volume,") and m.endswith(f"target={ENVIRONMENT_MOUNT}")
        for m in mounts
    )
    # The docker socket is the classic escape and must never appear.
    assert not any("docker.sock" in m for m in mounts)


def test_the_container_writes_as_the_host_user(tmp_path: Path) -> None:
    """Otherwise the run workspace ends up owned by root."""
    command = _runner(tmp_path)._container_command("c1", _request(tmp_path, "true"))
    assert command[command.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"


def test_resource_limits_reach_the_runtime(tmp_path: Path) -> None:
    runner = _runner(tmp_path, limits=ContainerLimits(memory="512m", cpus="1", pids=64))
    command = runner._container_command("c1", _request(tmp_path, "true"))
    assert command[command.index("--memory") + 1] == "512m"
    assert command[command.index("--cpus") + 1] == "1"
    assert command[command.index("--pids-limit") + 1] == "64"


def test_the_command_is_passed_as_argv_after_the_image(tmp_path: Path) -> None:
    """No shell, so nothing in the command is interpreted."""
    runner = _runner(tmp_path)
    command = runner._container_command(
        "c1", _request(tmp_path, "sh", "-c", "echo $HOME; rm -rf /")
    )
    assert command[command.index(PINNED) + 1 :] == [
        "sh",
        "-c",
        "echo $HOME; rm -rf /",
    ]


def test_working_directory_is_translated_into_the_container(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    at_root = runner._container_command("c1", _request(tmp_path, "true"))
    assert at_root[at_root.index("--workdir") + 1] == str(WORKSPACE_MOUNT)
    deeper = runner._container_command("c2", _request(nested, "true"))
    assert deeper[deeper.index("--workdir") + 1] == f"{WORKSPACE_MOUNT}/src/pkg"


def test_a_working_directory_outside_the_workspace_is_refused(tmp_path: Path) -> None:
    """The mount defines the boundary, so a cwd outside it is a bug, not a mount."""
    outside = tmp_path.parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    runner = _runner(tmp_path / "inside")
    (tmp_path / "inside").mkdir()
    with pytest.raises(ValueError, match="outside the mounted workspace"):
        runner._container_command("c1", _request(outside, "true"))


def test_each_command_gets_its_own_container_name(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    names = {runner._reserve_name() for _ in range(5)}
    assert len(names) == 5


def test_closing_refuses_further_work(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    assert runner.closing is False
    runner.close()
    assert runner.closing is True
    with pytest.raises(RuntimeError, match="closing"):
        runner.execute(_request(tmp_path, "true"))


def test_missing_runtime_reports_unavailable(tmp_path: Path) -> None:
    runner = _runner(tmp_path, runtime="definitely-not-a-container-runtime")
    with pytest.raises(RuntimeError, match="container runtime is unavailable"):
        runner.require_available()


# -- integration: needs a real daemon and an image already pulled -----------

_HAS_DOCKER = shutil.which("docker") is not None
_HAS_IMAGE = bool(INTEGRATION_IMAGE) and _HAS_DOCKER and (
    subprocess.run(
        ["docker", "image", "inspect", INTEGRATION_IMAGE],
        capture_output=True,
        check=False,
    ).returncode
    == 0
)
integration = pytest.mark.skipif(
    not _HAS_IMAGE,
    reason="set ASET_CONTAINER_TEST_IMAGE to a locally present image",
)


@integration
def test_real_container_runs_a_command_and_sees_the_workspace(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("from the host\n", encoding="utf-8")
    runner = ContainerRunner(
        tmp_path, image=INTEGRATION_IMAGE, allow_unpinned_image=True
    )
    try:
        runner.require_available()
        completed = runner.execute(_request(tmp_path, "cat", "hello.txt"))
        assert completed.returncode == 0
        assert "from the host" in completed.stdout
    finally:
        runner.close()


@integration
def test_real_container_has_no_network_unless_asked(tmp_path: Path) -> None:
    runner = ContainerRunner(
        tmp_path, image=INTEGRATION_IMAGE, allow_unpinned_image=True
    )
    try:
        completed = runner.execute(
            _request(tmp_path, "sh", "-c", "ls /sys/class/net")
        )
        interfaces = completed.stdout.split()
        assert interfaces == ["lo"], f"expected loopback only, got {interfaces}"
    finally:
        runner.close()


@integration
def test_real_container_writes_land_on_the_host_owned_by_the_host_user(
    tmp_path: Path,
) -> None:
    runner = ContainerRunner(
        tmp_path, image=INTEGRATION_IMAGE, allow_unpinned_image=True
    )
    try:
        completed = runner.execute(
            _request(tmp_path, "sh", "-c", "echo written > out.txt")
        )
        assert completed.returncode == 0, completed.stderr
        produced = tmp_path / "out.txt"
        assert produced.read_text(encoding="utf-8").strip() == "written"
        assert produced.stat().st_uid == os.getuid()
    finally:
        runner.close()


@integration
def test_real_container_is_killed_when_the_deadline_passes(tmp_path: Path) -> None:
    """The container bounds the runaway; there is no descendant left to hunt."""
    runner = ContainerRunner(
        tmp_path, image=INTEGRATION_IMAGE, allow_unpinned_image=True
    )
    try:
        request = CommandRequest(
            args=("sh", "-c", "sleep 120"),
            cwd=tmp_path,
            deadline=time.monotonic() + 3,
        )
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            runner.execute(request)
        assert time.monotonic() - started < 30
    finally:
        runner.close()


@integration
def test_real_container_cannot_reach_the_host_filesystem(tmp_path: Path) -> None:
    """Only the two mounts exist; the operator's home is not among them."""
    runner = ContainerRunner(
        tmp_path, image=INTEGRATION_IMAGE, allow_unpinned_image=True
    )
    try:
        completed = runner.execute(
            _request(tmp_path, "sh", "-c", f"ls {Path.home()} 2>&1 || true")
        )
        assert "No such file" in completed.stdout or completed.stdout.strip() == ""
    finally:
        runner.close()
