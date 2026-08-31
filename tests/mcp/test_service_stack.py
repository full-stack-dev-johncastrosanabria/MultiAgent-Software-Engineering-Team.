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


# -- when the project declares nothing (capability 4B) ------------------------


SPRING = """spring:
  datasource:
    url: ${DB_URL:jdbc:postgresql://localhost:5432/derived_db}
    username: ${DB_USER:appuser}
    password: ${DB_PASSWORD:apppass}
"""
SQLITE_ONLY = "SQLALCHEMY_DATABASE_URI = 'sqlite:///local.db'\n"


def _spring_project(tmp_path: Path) -> Path:
    resources = tmp_path / "svc" / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.yml").write_text(SPRING, encoding="utf-8")
    return tmp_path


def test_a_project_without_compose_derives_one(tmp_path: Path) -> None:
    stack = ServiceStack(_spring_project(tmp_path), run_id="derived")
    assert stack.declared is False, "the project declares nothing"
    assert stack.derived is True
    assert stack.services == ("postgres",)


def test_a_project_needing_nothing_derives_nothing(tmp_path: Path) -> None:
    """SQLite is a library. Inferring no services is the right answer."""
    (tmp_path / "config.py").write_text(SQLITE_ONLY, encoding="utf-8")
    stack = ServiceStack(tmp_path, run_id="none")
    assert stack.services == ()
    assert stack.derived is False


def test_a_declared_compose_is_never_overridden_by_inference(tmp_path: Path) -> None:
    """The project's own file wins; guessing over it would be presumptuous."""
    _spring_project(tmp_path)
    (tmp_path / "docker-compose.yml").write_text(
        MINIMAL.format(image=BASE), encoding="utf-8"
    )
    stack = ServiceStack(tmp_path, run_id="declared")
    assert stack.declared is True
    assert stack.derived is False
    assert stack.services == ("cache",)


def test_the_run_is_redirected_off_localhost(tmp_path: Path) -> None:
    """Inside the run `localhost` is the command's own container."""
    stack = ServiceStack(_spring_project(tmp_path), run_id="redirect")
    overrides = dict(stack.environment_for("jvm"))
    assert overrides["SPRING_DATASOURCE_URL"] == (
        "jdbc:postgresql://postgres:5432/derived_db"
    )


def test_the_delivery_artifacts_are_available_for_a_pull_request(tmp_path: Path) -> None:
    """What a developer would receive: ports on localhost, no plaintext secret."""
    stack = ServiceStack(_spring_project(tmp_path), run_id="deliver")
    compose, example = stack.delivery_artifacts()
    assert "5432:5432" in compose
    assert "apppass" not in compose, "the delivery artifact must not carry a password"
    assert "change-me" in example


@needs_docker
def test_derived_services_really_start(tmp_path: Path) -> None:
    if subprocess.run(
        ["docker", "image", "inspect", "postgres:17-alpine"],
        capture_output=True, check=False,
    ).returncode:
        pytest.skip("needs postgres pulled")
    stack = ServiceStack(_spring_project(tmp_path), run_id="derived-up")
    try:
        stack.up(time.monotonic() + 300)
        assert stack.network
    finally:
        stack.down()
