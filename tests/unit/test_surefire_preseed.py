"""What the closed network of ADR 14 needs cached before it closes.

Trial 2 of decision 14 failed with `surefire-junit-platform` unresolvable inside
the run's internal network, after a preparation phase that had network and
reported success. These tests hold the two properties that failure taught: the
provider is fetched by coordinate, and its version is read from the cache rather
than assumed.
"""

import subprocess
from pathlib import Path

from engineering_team.contracts.enums import AgentRole
from engineering_team.mcp.command import CommandRequest
from engineering_team.mcp.quality import (
    _SUREFIRE_PROVIDERS,
    QualityMCP,
    _surefire_providers,
)
from engineering_team.stacks import profile_for


def test_every_provider_is_fetched_rather_than_one_guessed() -> None:
    """Which provider Surefire picks depends on the target's test framework."""
    shell = _surefire_providers("/aset/env")
    for provider in _SUREFIRE_PROVIDERS:
        assert provider in shell
    assert "surefire-junit-platform" in _SUREFIRE_PROVIDERS


def test_the_version_is_read_from_the_cache_not_hardcoded() -> None:
    """A pinned version would be wrong the first time a target moves Surefire."""
    shell = _surefire_providers("/aset/env")
    assert "surefire-booter/*/" in shell
    assert "$version" in shell
    assert "3.5.6" not in shell


def test_the_fetch_uses_the_run_repository() -> None:
    """A provider warmed into another repository is a cache the run never reads."""
    shell = _surefire_providers("/aset/env")
    assert shell.count("/aset/env/m2") == 2
    assert "dependency:get" in shell


def test_preparation_never_selects_or_runs_test_code() -> None:
    """The invariant the preparation list exists under."""
    shell = _surefire_providers("/aset/env")
    assert " test" not in shell
    assert "-Dtest=" not in shell
    assert "surefire:test" not in shell


def test_a_failed_fetch_stops_the_preparation() -> None:
    """Otherwise the run enters the closed network with a half-warmed cache."""
    assert _surefire_providers("/aset/env").startswith("set -e;")


class _DaemonRecordingRunner:
    """Records commands, and claims a run-scoped daemon so preparation runs."""

    daemon = object()

    def __init__(self) -> None:
        self.requests: list[CommandRequest] = []
        self.environment: Path | None = Path("/recorded/env")
        self.closed = False

    def require_available(self) -> None:
        return None

    def prepare_scratch(self) -> Path:
        return Path("/recorded/env")

    def prepare_environment(self, deadline: float) -> str:
        return "/recorded/env/bin/python"

    @property
    def closing(self) -> bool:
        return self.closed

    def execute(self, request: CommandRequest) -> subprocess.CompletedProcess[str]:
        self.requests.append(request)
        return subprocess.CompletedProcess(list(request.args), 0, "", "")

    def close(self) -> None:
        self.closed = True


def test_preparation_does_not_replace_the_suite_command() -> None:
    """Trial 3: every preparation step passed and no test ever ran.

    The phase reported SUCCESS because the last preparation command was executed
    in the suite's place, so the only honest assertion is on what ran last.
    """
    runner = _DaemonRecordingRunner()
    quality = QualityMCP(
        Path.cwd(), runner=runner, profile=profile_for("jvm"), timeout_seconds=30,
    )
    quality.run_tests(AgentRole.TESTING)

    executed = [tuple(request.args) for request in runner.requests]
    assert len(executed) == 3, executed
    assert executed[0][:2] == ("mvn", "-B") and "dependency:go-offline" in executed[0]
    assert executed[1][0] == "sh"
    assert executed[-1][-1] == "test", executed[-1]
    assert "dependency:get" not in " ".join(executed[-1])
    assert executed[-1].count("test") == 1
