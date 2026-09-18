"""Completed advisory evidence is required before an unchanged-manifest exemption."""
import json
import os
import subprocess
from unittest.mock import Mock

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.quality import QualityMCP
from engineering_team.stacks import profile_for

NPM = {
    "auditReportVersion": 2,
    "vulnerabilities": {"lib": {"name": "lib", "severity": "high", "via": [
        {"title": "vulnerable lib", "url": "https://example.test/advisory", "severity": "high"}
    ]}},
    "metadata": {"vulnerabilities": {"high": 1, "critical": 0}},
}
DOTNET = {"version": 1, "projects": [{"path": "app.csproj", "frameworks": [{
    "framework": "net8.0", "topLevelPackages": [{"id": "Lib", "resolvedVersion": "1.0", "vulnerabilities": [
        {"severity": "High", "advisoryurl": "https://example.test/advisory"}
    ]}]
}]}]}
JVM = {"scanInfo": {"engineVersion": "13.0.0"}, "projectInfo": {"name": "app"},
       "dependencies": [{"fileName": "lib.jar", "vulnerabilities": [
           {"name": "CVE-2026-12345", "cvssv3": {"baseScore": 8.1}}
       ]}]}
JVM_OUTPUT = "One or more dependencies were identified with vulnerabilities that have a CVSS score greater than or equal to '7.0'"


def run_scan(tmp_path, monkeypatch, stack, output, code, report=None, report_mode="fresh", phase="security"):
    quality = QualityMCP(tmp_path, runner=Mock(), profile=profile_for(stack))
    monkeypatch.setattr(quality, "_sandbox_directory", lambda: "/aset/env")
    if report_mode == "stale":
        target = tmp_path / "target"
        target.mkdir(exist_ok=True)
        (target / "dependency-check-report.json").write_text(json.dumps(JVM))

    def execute(args, **kwargs):
        if stack == "jvm" and report is not None:
            # dependency-check-maven reads its report directory from the user
            # property odc.outputDirectory. Measured 2026-09-16 on spring-demo:
            # given -DoutputDirectory it ignored it and wrote target/, so real
            # advisories were never confirmed.
            directories = [part.split("=", 1)[1] for part in args if part.startswith("-Dodc.outputDirectory=")]
            if directories:
                path = tmp_path / directories[0] / "dependency-check-report.json"
                if report_mode == "fifo":
                    os.mkfifo(path)
                elif report_mode == "symlink":
                    outside = tmp_path.parent / "outside-report.json"
                    outside.write_text(json.dumps(report))
                    path.symlink_to(outside)
                else:
                    path.write_text(json.dumps(report))
        return subprocess.CompletedProcess(args, code, output, "")

    monkeypatch.setattr(quality, "_execute_process", execute)
    return quality._run_profile(AgentRole.SECURITY, "run_security_scan", phase, [], {AgentRole.SECURITY}, quality._deadline())


@pytest.mark.parametrize("stack,output,code,report", [
    ("node", json.dumps(NPM), 1, None),
    ("dotnet", "Restore complete\n" + json.dumps(DOTNET) + "\n" + "x" * 6000, 0, None),
    ("jvm", JVM_OUTPUT, 1, JVM),
])
def test_completed_advisories_are_confirmed_without_losing_fail(tmp_path, monkeypatch, stack, output, code, report):
    result = run_scan(tmp_path, monkeypatch, stack, output, code, report)
    assert result.status is ToolStatus.FAIL
    assert result.confirmed_dependency_findings is True
    assert "lib" in result.output_summary.lower() or "CVE-2026-12345" in result.output_summary


@pytest.mark.parametrize("stack,output,code,report,report_mode", [
    ("node", "unexpected install failure", 1, None, "fresh"),
    ("node", json.dumps({**NPM, "error": {"code": "EUNKNOWN"}}), 1, None, "fresh"),
    ("node", json.dumps(NPM), 2, None, "fresh"),
    ("dotnet", json.dumps({**DOTNET, "logs": [{"level": "error", "message": "missing project"}]}), 0, None, "fresh"),
    ("dotnet", json.dumps(DOTNET), 1, None, "fresh"),
    ("jvm", JVM_OUTPUT, 1, None, "stale"),
    ("jvm", JVM_OUTPUT, 1, JVM, "symlink"),
    ("jvm", JVM_OUTPUT, 1, JVM, "fifo"),
    ("jvm", JVM_OUTPUT, 1, {**JVM, "scanInfo": {"engineVersion": "13", "analysisExceptions": ["bad analyzer"]}}, "fresh"),
    ("jvm", "unknown scanner failure", 1, JVM, "fresh"),
    ("jvm", JVM_OUTPUT, 1, {"dependencies": "malformed"}, "fresh"),
])
def test_incomplete_scans_never_confirm_findings(tmp_path, monkeypatch, stack, output, code, report, report_mode):
    result = run_scan(tmp_path, monkeypatch, stack, output, code, report, report_mode)
    assert result.confirmed_dependency_findings is False
    assert not list(tmp_path.glob(".aset-advisories-*"))


def test_dependency_resolution_does_not_confirm_advisories(tmp_path, monkeypatch):
    result = run_scan(tmp_path, monkeypatch, "node", json.dumps(NPM), 1, phase="dependency")
    assert result.status is ToolStatus.FAIL
    assert result.confirmed_dependency_findings is False


def test_cached_security_report_retains_confirmed_provenance(tmp_path):
    from engineering_team.contracts.models import ToolResult

    quality = QualityMCP(tmp_path, runner=Mock(), profile=profile_for("node"))
    previous = ToolResult(
        tool_name="run_security_scan", allowed_role=AgentRole.SECURITY,
        status=ToolStatus.FAIL, input_summary="safe", output_summary="advisory lib",
        duration_ms=1, scans_dependencies=True, confirmed_dependency_findings=True,
        evidence_reference="mcp://quality/run_security_scan#client",
    )
    quality._last["run_security_scan"] = previous
    cached = quality.get_security_report(AgentRole.SECURITY)
    assert cached.status is ToolStatus.FAIL
    assert cached.scans_dependencies and cached.confirmed_dependency_findings
    assert cached.evidence_reference == previous.evidence_reference


@pytest.mark.parametrize("payload", [
    {"version": 1, "projects": [], "logs": [{"level": "error", "message": "failed to evaluate one project"}]},
    {"version": 1, "projects": [], "errors": ["advisory service failed"]},
    {"version": 2, "projects": []},
    {"version": True, "projects": []},
    {"projects": []},
    {"version": 1, "projects": {}},
    {"version": 1, "projects": [None]},
    {"version": 1, "projects": [{"frameworks": {}}]},
    {"version": 1, "projects": [{"frameworks": [{"topLevelPackages": {}}]}]},
], ids=["error-log", "errors", "future-version", "bool-version", "missing-version", "bad-projects", "null-project", "bad-frameworks", "bad-packages"])
def test_dotnet_zero_exit_with_incomplete_evidence_is_unavailable(tmp_path, monkeypatch, payload):
    result = run_scan(tmp_path, monkeypatch, "dotnet", json.dumps(payload), 0)
    assert result.status is ToolStatus.UNAVAILABLE
    assert not result.confirmed_dependency_findings
    assert result.error and "INFRASTRUCTURE_ERROR" in result.error


@pytest.mark.parametrize("payload", [
    {"version": 1, "projects": []},
    {"version": 1, "projects": [{"path": "app.csproj", "frameworks": [{
        "framework": "net8.0", "topLevelPackages": [{"id": "Safe", "resolvedVersion": "1.0"}],
    }]}], "logs": [{"level": "warning", "message": "harmless warning"}]},
])
def test_dotnet_supported_clean_reports_still_pass(tmp_path, monkeypatch, payload):
    result = run_scan(tmp_path, monkeypatch, "dotnet", "Restore complete\n" + json.dumps(payload), 0)
    assert result.status is ToolStatus.SUCCESS
    assert not result.confirmed_dependency_findings


@pytest.mark.parametrize("stack", ["node", "dotnet"])
def test_container_keeps_large_advisory_stdout_separate_from_notices(tmp_path, monkeypatch, stack):
    """Exercise the actual buffering boundary, not a full-output fake runner."""
    from io import BytesIO

    from engineering_team.mcp.container import ContainerRunner

    payload = {**(NPM if stack == "node" else DOTNET), "padding": "x" * 12000}
    stdout = json.dumps(payload).encode()

    class Process:
        def __init__(self, *args, **kwargs):
            self.stdout = BytesIO(stdout)
            self.stderr = BytesIO(b"npm notice: a newer version is available\n")
            self.returncode = 1 if stack == "node" else 0

        def wait(self, timeout):
            return self.returncode

    runner = ContainerRunner(tmp_path, image=profile_for(stack).image)
    monkeypatch.setattr(runner, "_ensure_volume", lambda: None)
    monkeypatch.setattr(runner, "_quiet", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    monkeypatch.setattr(subprocess, "Popen", Process)
    quality = QualityMCP(tmp_path, runner=runner, profile=profile_for(stack))
    monkeypatch.setattr(quality, "_sandbox_directory", lambda: "/aset/env")
    result = quality._run_profile(AgentRole.SECURITY, "run_security_scan", "security", [], {AgentRole.SECURITY}, quality._deadline())
    assert result.status is ToolStatus.FAIL
    assert result.confirmed_dependency_findings
    assert len(result.output_summary) <= 4000


@pytest.mark.parametrize("stack", ["node", "dotnet"])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("failure", ["overflow", OSError, ValueError])
def test_truncated_scanner_output_cannot_confirm_findings_or_success(tmp_path, monkeypatch, stack, stream, failure):
    from io import BytesIO

    from engineering_team.mcp.command import _STRUCTURED_OUTPUT_LIMIT
    from engineering_team.mcp.container import ContainerRunner

    payload = json.dumps(NPM if stack == "node" else DOTNET).encode()

    class BrokenStream(BytesIO):
        def read(self, size=-1):
            chunk = super().read(size)
            if not chunk:
                raise failure("stream failed before EOF")
            return chunk

    class Process:
        def __init__(self, *args, **kwargs):
            # A complete JSON object remains at the tail. Only the explicit
            # truncation signal can prove that preceding diagnostics were lost.
            self.stdout = BytesIO((b"x" * _STRUCTURED_OUTPUT_LIMIT if stream == "stdout" and failure == "overflow" else b"") + payload)
            self.stderr = BytesIO(b"x" * (_STRUCTURED_OUTPUT_LIMIT + 1) if stream == "stderr" and failure == "overflow" else b"")
            if failure != "overflow":
                setattr(self, stream, BrokenStream(payload if stream == "stdout" else b"notice\n"))
            self.returncode = 1 if stack == "node" else 0

        def wait(self, timeout):
            return self.returncode

    runner = ContainerRunner(tmp_path, image=profile_for(stack).image)
    monkeypatch.setattr(runner, "_ensure_volume", lambda: None)
    monkeypatch.setattr(runner, "_quiet", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    monkeypatch.setattr(subprocess, "Popen", Process)
    quality = QualityMCP(tmp_path, runner=runner, profile=profile_for(stack))
    monkeypatch.setattr(quality, "_sandbox_directory", lambda: "/aset/env")
    result = quality._run_profile(AgentRole.SECURITY, "run_security_scan", "security", [], {AgentRole.SECURITY}, quality._deadline())
    assert result.status is ToolStatus.UNAVAILABLE
    assert not result.confirmed_dependency_findings
    assert len(result.output_summary) <= 4000


def _go_scan_with_head(tmp_path, monkeypatch, *, head: str, tail: str):
    """A Go security scan whose runner restored a head window ahead of its tail.

    Go's security phase is the one non-structured path that reaches
    `_security_infrastructure_error`, so it is the one where the 64 KiB head
    `ContainerRunner` retains (task 4) could reach that text heuristic too.
    """
    from engineering_team.mcp.command import CommandOutput

    quality = QualityMCP(tmp_path, runner=Mock(), profile=profile_for("go"))
    monkeypatch.setattr(quality, "_sandbox_directory", lambda: "/aset/env")
    monkeypatch.setattr(
        quality, "_execute_process",
        lambda args, **_kwargs: CommandOutput(
            args, 0, tail, "", output_truncated=True, stdout_head=head,
        ),
    )
    return quality._run_profile(
        AgentRole.SECURITY, "run_security_scan", "security", [],
        {AgentRole.SECURITY}, quality._deadline(),
    )


def test_an_early_network_blip_in_a_long_go_scan_log_does_not_flip_it_to_unavailable(
    tmp_path, monkeypatch,
):
    """The head window restores build errors for extraction; it must not widen
    the pre-existing outage heuristic, which has always read the tail only. A
    transient `dial tcp:` early in a download log that the scan then recovered
    from is not an advisory service that was unavailable."""
    head = (
        "go: downloading example.test/mod v1.0.0\n"
        "dial tcp: lookup proxy.golang.org: i/o timeout\n"
        + "go: downloading example.test/other v1.0.0\n" * 200
    )
    result = _go_scan_with_head(
        tmp_path, monkeypatch, head=head, tail="No vulnerabilities found.\n",
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.error_code is None


def test_the_same_marker_in_the_tail_still_reports_the_scanner_outage(
    tmp_path, monkeypatch,
):
    """Control: the heuristic itself is unchanged -- only its input window is."""
    result = _go_scan_with_head(
        tmp_path, monkeypatch, head="",
        tail="govulncheck: dial tcp: lookup vuln.go.dev: no such host\n",
    )

    assert result.status is ToolStatus.UNAVAILABLE
    assert result.error and "INFRASTRUCTURE_ERROR" in result.error
