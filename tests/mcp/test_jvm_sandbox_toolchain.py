"""What a JVM component needs from the sandbox that a Python one does not.

Measured against `order-ms` at the multistack base commit: under the process
sandbox its suite reported 24 errors where the same commit on the host reported
one, and every extra error was `Could not initialize plugin: MockMaker`. Two
independent causes, one test each here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole
from engineering_team.mcp.quality import QualityMCP
from engineering_team.stacks import profile_for


def _cache(environment: Path, version: str = "5.23.0") -> Path:
    jar = (
        environment
        / "m2"
        / "org"
        / "mockito"
        / "mockito-core"
        / version
        / f"mockito-core-{version}.jar"
    )
    jar.parent.mkdir(parents=True, exist_ok=True)
    jar.write_bytes(b"")
    return jar


class _Runner:
    """A runner that records what it was asked to run, and grants nothing."""

    def __init__(self, environment: Path) -> None:
        self.environment = environment
        self.calls: list[dict] = []

    def require_available(self) -> None:
        return None

    @property
    def closing(self) -> bool:
        return False

    def prepare_environment(self, deadline: float) -> str:
        return str(self.environment / "bin" / "python")

    def execute(self, request) -> subprocess.CompletedProcess[str]:
        self.calls.append({
            "args": list(request.args),
            "allow_network": request.allow_network,
            "allow_subprocesses": request.allow_subprocesses,
        })
        return subprocess.CompletedProcess(list(request.args), 0, "", "")

    def close(self) -> None:
        return None


def _quality(tmp_path: Path, stack: str = "jvm") -> tuple[QualityMCP, _Runner]:
    environment = tmp_path / "env"
    environment.mkdir(exist_ok=True)
    runner = _Runner(environment)
    component = tmp_path / "component"
    component.mkdir(exist_ok=True)
    return (
        QualityMCP(
            component,
            timeout_seconds=60,
            runner=runner,
            profile=profile_for(stack),
            component="order-ms",
        ),
        runner,
    )


def test_test_phase_loads_mockito_as_an_agent_instead_of_self_attaching(
    tmp_path: Path,
) -> None:
    quality, runner = _quality(tmp_path)
    jar = _cache(runner.environment)

    quality.run_tests(AgentRole.TESTING)

    argument = f"-DargLine=-javaagent:{jar}"
    assert any(argument in call["args"] for call in runner.calls), runner.calls


def test_component_without_mockito_is_passed_no_agent(tmp_path: Path) -> None:
    quality, runner = _quality(tmp_path)

    quality.run_tests(AgentRole.TESTING)

    assert not any(
        part.startswith("-DargLine=") for call in runner.calls for part in call["args"]
    )


def test_an_ambiguous_cache_is_skipped_rather_than_guessed_at(tmp_path: Path) -> None:
    quality, runner = _quality(tmp_path)
    _cache(runner.environment, "5.23.0")
    _cache(runner.environment, "5.14.0")

    quality.run_tests(AgentRole.TESTING)

    assert not any(
        part.startswith("-DargLine=") for call in runner.calls for part in call["args"]
    )


def test_python_component_is_never_given_a_java_agent(tmp_path: Path) -> None:
    quality, runner = _quality(tmp_path, stack="python")
    _cache(runner.environment)

    assert quality._java_agent_arguments("test", str(runner.environment)) == []


@pytest.mark.parametrize("stack, expected", [("jvm", True), ("python", False)])
def test_forking_is_declared_by_the_toolchain_not_by_network_access(
    stack: str, expected: bool
) -> None:
    """`mvn` is a shell script: denied a fork it never reaches a single test.

    Coupling the two permissions meant only a phase that also reached the
    network could start its own launcher, so an offline Maven phase died on
    `fork: Operation not permitted`. Python's entry points exec without forking
    and keep the tighter sandbox.
    """
    assert profile_for(stack).needs_subprocesses is expected
