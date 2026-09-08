"""Which failures are somebody else's dependencies, and which are our code.

Trial 8b rejected order-ms over CVE-2026-41115 in kafka-clients and
CVE-2026-75838 in swagger-ui: versions published before the change, in a pom it
never opened. The exemption for exactly that case did not apply, because it
asked the tool's name and the JVM reports those CVEs through the same name
Python uses for ruff.
"""

from __future__ import annotations

import pytest

from engineering_team.contracts.enums import ActionMode, AgentRole, ToolStatus
from engineering_team.contracts.models import ImplementationResult, ToolResult
from engineering_team.contracts.state import EngineeringState
from engineering_team.agents.security import SecurityAgent
from engineering_team.models.context import build_context
from engineering_team.stacks import profile_for

ORDER = ["order-ms/src/main/java/com/prueba/orderms/domain/Order.java"]
POM = ["order-ms/pom.xml", *ORDER]


def _reviewed(
    tool_name: str, scans_dependencies: bool, changed_files: list[str]
):
    tool = ToolResult(
        tool_name=tool_name,
        allowed_role=AgentRole.SECURITY,
        status=ToolStatus.FAIL,
        input_summary="project",
        duration_ms=1,
        output_summary="CVE-2026-41115 kafka-clients, CVE-2026-75838 swagger-ui",
        scans_dependencies=scans_dependencies,
    )
    state = EngineeringState(
        run_id="r",
        requirement="Reject nonpositive quantity",
        tool_results=[tool],
        implementation=ImplementationResult(
            action_mode=ActionMode.APPLIED,
            changed_files=changed_files,
            diff="allowlist-only order changes",
            evidence=["mcp://repository/update_file"],
            validation_result="compile ok",
            security_surface_changed=False,
        ),
    )
    return SecurityAgent().execute(build_context(AgentRole.SECURITY, state, "scan"))


def test_jvm_dependency_cves_in_an_untouched_manifest_are_baseline_risk() -> None:
    reviewed = _reviewed("run_security_scan", True, ORDER)

    assert reviewed.status.value == "PASS"
    assert [finding.category for finding in reviewed.findings] == [
        "baseline dependencies"
    ]


def test_the_same_cves_block_once_the_change_edits_the_manifest() -> None:
    reviewed = _reviewed("run_security_scan", True, POM)

    assert reviewed.status.value == "FAIL"
    assert [finding.category for finding in reviewed.findings] == ["security tooling"]


def test_a_linter_under_the_same_tool_name_is_never_held_as_baseline() -> None:
    """The safety property: ruff reports our own code, and must still block.

    `run_security_scan` names the phase, not what the phase looks at. Exempting
    by name would have cleared every Python code finding along with the JVM's
    third-party CVEs.
    """
    reviewed = _reviewed("run_security_scan", False, ORDER)

    assert reviewed.status.value == "FAIL"
    assert [finding.category for finding in reviewed.findings] == ["security tooling"]


@pytest.mark.parametrize(
    "stack, expected",
    [
        ("python", ("dependency",)),
        ("jvm", ("dependency", "security")),
        ("node", ("dependency", "security")),
        ("dotnet", ("dependency", "security")),
        ("go", ("dependency", "security")),
    ],
)
def test_only_python_reports_its_own_code_from_the_security_phase(
    stack: str, expected: tuple[str, ...]
) -> None:
    """Python is the exception the old list was written from.

    Its security phase is ruff. Every other profile runs a vulnerability
    database lookup there -- dependency-check, npm audit, dotnet list
    --vulnerable, govulncheck -- so four of five stacks were classified by a
    rule derived from the fifth.
    """
    assert profile_for(stack).dependency_scan_phases == expected
