"""The runner seam: quality depends on the interface, not on the sandbox.

These tests exist to prove the seam is real. If a container backend can be
dropped in without touching `quality.py`, ADR 2 is an additive change; if it
cannot, the split in ADR 3 did not actually happen.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import time
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.command import CommandRequest, CommandRunner
from engineering_team.mcp.quality import QualityMCP
from engineering_team.stacks import profile_for


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

    def prepare_scratch(self) -> Path:
        if self.environment is None:
            self.environment = Path("/recorded/env")
        return self.environment

    def prepare_environment(self, deadline: float) -> str:
        self.prepare_scratch()
        return "/recorded/env/bin/python"

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


class NoPythonRecordingRunner(RecordingRunner):
    """Record native toolchain commands and reject Python provisioning."""

    def __init__(self, *, exit_code: int = 0, stdout: str = "") -> None:
        super().__init__(exit_code=exit_code, stdout=stdout)
        self.environment = Path("/recorded/env")

    def prepare_environment(self, deadline: float) -> str:
        raise AssertionError("a non-Python security operation prepared Python")




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


@pytest.mark.parametrize(
    ("stack", "operation_name", "needs_network"),
    [
        ("python", "scan_dependencies", False),
        ("python", "run_security_scan", False),
        ("jvm", "scan_dependencies", True),
        ("jvm", "run_security_scan", True),
        ("node", "scan_dependencies", False),
        ("node", "run_security_scan", True),
        ("dotnet", "scan_dependencies", True),
        ("dotnet", "run_security_scan", True),
        ("go", "scan_dependencies", True),
        ("go", "run_security_scan", True),
    ],
)
def test_profile_scan_network_policy_reaches_command_request(
    tmp_path: Path,
    stack: str,
    operation_name: str,
    needs_network: bool,
) -> None:
    runner = (
        RecordingRunner()
        if stack == "python"
        else NoPythonRecordingRunner(
            stdout=(
                json.dumps({"projects": []})
                if stack == "dotnet" and operation_name == "run_security_scan"
                else ""
            )
        )
    )
    quality = QualityMCP(
        tmp_path,
        runner=runner,
        profile=profile_for(stack),
    )

    result = getattr(quality, operation_name)(AgentRole.SECURITY)

    assert result.status is ToolStatus.SUCCESS
    assert runner.requests[-1].allow_network is needs_network
    assert runner.requests[-1].allow_subprocesses is needs_network


def test_jvm_security_operations_use_maven_without_preparing_python(
    tmp_path: Path,
) -> None:
    runner = NoPythonRecordingRunner()
    quality = QualityMCP(
        tmp_path,
        runner=runner,
        profile=profile_for("jvm"),
        component="backend",
    )

    dependency = quality.scan_dependencies(AgentRole.SECURITY)
    security = quality.run_security_scan(AgentRole.SECURITY)

    assert dependency.status is ToolStatus.SUCCESS
    assert security.status is ToolStatus.SUCCESS
    assert [request.args[0] for request in runner.requests] == ["mvn", "mvn"]
    assert not any(
        "python" in part
        for request in runner.requests
        for part in request.args
    )
    assert dependency.evidence_reference == "mcp://quality/scan_dependencies#backend"
    assert security.evidence_reference == "mcp://quality/run_security_scan#backend"


def test_jvm_advisory_failure_is_unavailable_not_a_dependency_finding(
    tmp_path: Path,
) -> None:
    runner = NoPythonRecordingRunner(
        exit_code=1,
        stdout="Unable to continue dependency-check analysis: NvdApiException",
    )
    quality = QualityMCP(
        tmp_path,
        runner=runner,
        profile=profile_for("jvm"),
        component="backend",
    )

    result = quality.run_security_scan(AgentRole.SECURITY)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "INFRASTRUCTURE_ERROR" in (result.error or "")
    assert result.evidence_reference == "mcp://quality/run_security_scan#backend"


@pytest.mark.parametrize(
    ("template_field", "operation_name"),
    [
        ("dependency_template", "scan_dependencies"),
        ("security_template", "run_security_scan"),
    ],
)
def test_missing_security_operation_fails_closed_with_component_evidence(
    tmp_path: Path,
    template_field: str,
    operation_name: str,
) -> None:
    profile = dataclasses.replace(
        profile_for("jvm"),
        **{template_field: None},
    )
    runner = NoPythonRecordingRunner()
    quality = QualityMCP(
        tmp_path,
        runner=runner,
        profile=profile,
        component="backend",
    )

    result = getattr(quality, operation_name)(AgentRole.SECURITY)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "defines no" in (result.error or "")
    assert result.evidence_reference == f"mcp://quality/{operation_name}#backend"
    assert runner.requests == []


def test_dotnet_json_vulnerability_output_changes_success_to_failure(
    tmp_path: Path,
) -> None:
    runner = NoPythonRecordingRunner(
        stdout=(
            "warning {not-json}\n"
            + json.dumps({
                "projects": [{
                    "frameworks": [{
                        "topLevelPackages": [{
                            "id": "Example.Package",
                            "vulnerabilities": [{
                                "severity": "High",
                                "advisoryurl": "https://example.invalid/advisory",
                            }],
                        }],
                    }],
                }],
                "padding": "x" * 5000,
            })
            + "\nwarning with trailing }"
        )
    )
    quality = QualityMCP(
        tmp_path,
        runner=runner,
        profile=profile_for("dotnet"),
    )

    result = quality.run_security_scan(AgentRole.SECURITY)

    assert result.status is ToolStatus.FAIL


def test_dotnet_invalid_json_evidence_is_unavailable(tmp_path: Path) -> None:
    runner = NoPythonRecordingRunner(stdout="warning: scan produced no JSON")
    quality = QualityMCP(
        tmp_path,
        runner=runner,
        profile=profile_for("dotnet"),
    )

    result = quality.run_security_scan(AgentRole.SECURITY)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "INFRASTRUCTURE_ERROR" in (result.error or "")


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




