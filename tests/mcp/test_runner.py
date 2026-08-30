"""The runner seam: quality depends on the interface, not on the sandbox.

These tests exist to prove the seam is real. If a container backend can be
dropped in without touching `quality.py`, ADR 2 is an additive change; if it
cannot, the split in ADR 3 did not actually happen.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.runner import (
    CommandRequest,
    CommandRunner,
    ProcessRunner,
)


class RecordingRunner:
    """A runner that records commands instead of running them."""

    def __init__(self, *, exit_code: int = 0, stdout: str = "") -> None:
        self.requests: list[CommandRequest] = []
        self.closed = False
        self._exit_code = exit_code
        self._stdout = stdout
        self.environment: Path | None = None

    def require_available(self) -> None:
        return None

    @property
    def closing(self) -> bool:
        return self.closed

    def execute(self, request: CommandRequest) -> subprocess.CompletedProcess[str]:
        self.requests.append(request)
        return subprocess.CompletedProcess(
            list(request.args), self._exit_code, self._stdout, ""
        )

    def close(self) -> None:
        self.closed = True


def test_process_runner_stands_alone_without_quality() -> None:
    """The sandbox no longer needs a QualityMCP to exist."""
    runner = ProcessRunner(Path.cwd())
    assert isinstance(runner, CommandRunner)
    assert runner.environment is None
    assert runner.closing is False
    runner.close()
    assert runner.closing is True


def test_recording_runner_satisfies_the_interface() -> None:
    """A backend that is not a process sandbox is still a runner.

    This is the shape a container backend will have.
    """
    assert isinstance(RecordingRunner(), CommandRunner)


def test_quality_uses_the_injected_runner_and_never_starts_a_process() -> None:
    """Quality decides which commands to run; the runner decides how."""
    runner = RecordingRunner()
    quality = QualityMCP(Path.cwd(), runner=runner)

    assert quality._runner is runner
    # The environment is the runner's to grant, so quality reads it through it.
    marker = Path("/tmp/aset-seam-check")
    quality._environment = marker
    assert runner.environment == marker

    completed = quality._execute_process(
        ["echo", "seam"], cwd=Path.cwd(), deadline=time.monotonic() + 5
    )
    assert completed.returncode == 0
    assert len(runner.requests) == 1
    request = runner.requests[0]
    assert request.args == ("echo", "seam")
    assert request.allow_network is False
    assert request.allow_subprocesses is False


def test_network_and_fork_permissions_reach_the_runner_verbatim() -> None:
    """Only install phases may reach the network, and the runner is told so."""
    runner = RecordingRunner()
    quality = QualityMCP(Path.cwd(), runner=runner)
    quality._execute_process(
        ["pip", "install", "x"],
        cwd=Path.cwd(),
        deadline=time.monotonic() + 5,
        allow_network=True,
        allow_subprocesses=True,
    )
    request = runner.requests[-1]
    assert request.allow_network is True
    assert request.allow_subprocesses is True


def test_closing_quality_closes_its_runner() -> None:
    runner = RecordingRunner()
    quality = QualityMCP(Path.cwd(), runner=runner)
    quality.close()
    assert runner.closed is True


def test_quality_refuses_when_the_runner_reports_no_boundary() -> None:
    """An unsupported host fails before any command is built."""

    class UnavailableRunner(RecordingRunner):
        def require_available(self) -> None:
            raise RuntimeError("quality process sandbox is unavailable")

    runner = UnavailableRunner()
    quality = QualityMCP(Path.cwd(), runner=runner)
    result = quality.run_tests(AgentRole.TESTING)
    assert result.status is not ToolStatus.SUCCESS
    assert runner.requests == []


@pytest.mark.skipif(
    sys.platform not in ("darwin", "linux"), reason="sandbox backend is host-specific"
)
def test_process_runner_still_runs_a_real_command(tmp_path: Path) -> None:
    """The extraction kept a working runner, not just the shape of one."""
    runner = ProcessRunner(tmp_path)
    runner.environment = tmp_path
    completed = runner.execute(
        CommandRequest(
            args=("/bin/echo", "bounded"),
            cwd=tmp_path,
            deadline=time.monotonic() + 30,
        )
    )
    assert completed.returncode == 0
    assert "bounded" in completed.stdout
    runner.close()


@pytest.mark.skipif(
    sys.platform not in ("darwin", "linux"), reason="sandbox backend is host-specific"
)
def test_process_runner_still_denies_reads_outside_its_roots(tmp_path: Path) -> None:
    """The boundary survived the move.

    `sys.executable` is the operator's own virtual environment, outside the
    workspace and the ephemeral environment the runner grants. Launching it must
    fail on its own configuration file rather than start an interpreter that can
    see the operator's site-packages.
    """
    runner = ProcessRunner(tmp_path)
    runner.environment = tmp_path
    completed = runner.execute(
        CommandRequest(
            args=(sys.executable, "-c", "print('escaped')"),
            cwd=tmp_path,
            deadline=time.monotonic() + 30,
        )
    )
    assert completed.returncode != 0
    assert "escaped" not in completed.stdout
    assert "not permitted" in completed.stderr.lower()
    runner.close()
