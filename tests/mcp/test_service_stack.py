"""Services live for the run, not for a command (ADR 5).

The Docker-backed tests use a synthetic single-service compose so the suite stays
fast and does not require the project's heavy images. The end-to-end smoke test
against a real repository lives in test_service_stack_e2e.py.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from engineering_team.contracts.enums import ErrorCode
from engineering_team.services import ServiceStack, ServiceStartupError

MINIMAL = """services:
  cache:
    image: {image}
    command: ["sleep", "300"]
    ports: ["6399:6399"]
  app:
    build: .
"""

WITH_DATABASE = """services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: probe
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      retries: 20
"""
BASE = "debian:bookworm-slim"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode:
        return False
    return subprocess.run(
        ["docker", "image", "inspect", BASE], capture_output=True, check=False
    ).returncode == 0


needs_docker = pytest.mark.skipif(
    not _docker_ready(), reason="needs a running daemon and the base image"
)


def _project(tmp_path: Path, image: str = BASE) -> Path:
    (tmp_path / "docker-compose.yml").write_text(
        MINIMAL.format(image=image), encoding="utf-8"
    )
    return tmp_path


def test_infrastructure_failure_has_its_own_error_code() -> None:
    """A service that never started is not the Developer's defective code."""
    assert ErrorCode.INFRASTRUCTURE_ERROR


def test_a_project_without_compose_has_no_stack(tmp_path: Path) -> None:
    stack = ServiceStack(tmp_path, run_id="r1")
    assert stack.declared is False
    assert stack.network is None


def test_the_stack_reads_only_infrastructure(tmp_path: Path) -> None:
    stack = ServiceStack(_project(tmp_path), run_id="r1")
    assert stack.services == ("cache",), "a build: service must not be started"


@needs_docker
def test_services_start_and_share_an_internal_network(tmp_path: Path) -> None:
    stack = ServiceStack(_project(tmp_path), run_id="net-probe")
    try:
        stack.up(time.monotonic() + 240)
        assert stack.network
        internal = subprocess.run(
            ["docker", "network", "inspect", stack.network, "-f", "{{.Internal}}"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        assert internal == "true", "the services network must have no route out"
    finally:
        stack.down()


@needs_docker
def test_no_port_reaches_the_host(tmp_path: Path) -> None:
    """The compose file publishes 6399; the override must remove it."""
    stack = ServiceStack(_project(tmp_path), run_id="port-probe")
    try:
        stack.up(time.monotonic() + 240)
        bindings = subprocess.run(
            ["docker", "inspect", "-f",
             "{{range $p, $b := .HostConfig.PortBindings}}{{$p}} {{end}}",
             f"{stack.project}-cache-1"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        assert bindings == "", f"published to the host: {bindings}"
    finally:
        stack.down()


@needs_docker
def test_down_removes_everything_it_created(tmp_path: Path) -> None:
    stack = ServiceStack(_project(tmp_path), run_id="teardown")
    stack.up(time.monotonic() + 240)
    network = stack.network
    stack.down()
    remaining = subprocess.run(
        ["docker", "network", "ls", "-q", "-f", f"name={network}"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    assert remaining == "", "the run's network outlived the run"


@needs_docker
def test_a_service_that_cannot_start_is_reported_as_infrastructure(tmp_path: Path) -> None:
    """Not as a failing test: that is finding 7's misleading headline again."""
    stack = ServiceStack(_project(tmp_path, image="aset/does-not-exist:0"), run_id="bad")
    try:
        with pytest.raises(ServiceStartupError) as raised:
            stack.up(time.monotonic() + 120)
        assert raised.value.code is ErrorCode.INFRASTRUCTURE_ERROR
    finally:
        stack.down()


def _postgres_ready() -> bool:
    return _docker_ready() and subprocess.run(
        ["docker", "image", "inspect", "postgres:16-alpine"],
        capture_output=True, check=False,
    ).returncode == 0


@pytest.mark.skipif(not _postgres_ready(), reason="needs postgres:16-alpine pulled")
def test_a_command_reaches_the_projects_database_and_nothing_else(tmp_path: Path) -> None:
    """The whole point of ADR 5, end to end.

    A component's command runs in its own container on the run's internal network,
    resolves the database by the name the compose file gave it, and still has no
    route off that network.
    """
    from engineering_team.mcp.container import ContainerRunner
    from engineering_team.mcp.runner import CommandRequest

    (tmp_path / "docker-compose.yml").write_text(WITH_DATABASE, encoding="utf-8")
    stack = ServiceStack(tmp_path, run_id="reach")
    try:
        stack.up(time.monotonic() + 300)
        runner = ContainerRunner(
            tmp_path,
            image="postgres:16-alpine",
            allow_unpinned_image=True,
            network=stack.network,
        )
        try:
            reached = runner.execute(CommandRequest(
                args=("pg_isready", "-h", "db", "-U", "postgres"),
                cwd=tmp_path, deadline=time.monotonic() + 120,
            ))
            assert reached.returncode == 0, reached.stderr

            escaped = runner.execute(CommandRequest(
                args=("sh", "-c", "cat /proc/net/route | tail -n +2 | wc -l"),
                cwd=tmp_path, deadline=time.monotonic() + 60,
            ))
            assert escaped.stdout.strip() != "0", "no route to the database at all"
        finally:
            runner.close()
    finally:
        stack.down()
