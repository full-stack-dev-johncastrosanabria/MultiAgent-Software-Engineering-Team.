"""One failing component must not be hidden by a later passing one.

With ADR 4 a run produces one `run_tests` result per component — ten of them for
BusinessAI-Analytics. Both gates read `run_tests[-1]`, so the verdict came from
whichever component happened to run last.
"""

from __future__ import annotations

from engineering_team.agents.reviewer import ReviewerAgent
from engineering_team.agents.testing import TestingAgent
from engineering_team.contracts.enums import AgentRole, ReviewerStatus, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.contracts.state import EngineeringState
from engineering_team.models.context import build_context


def _component_result(component: str, status: ToolStatus) -> ToolResult:
    return ToolResult(
        tool_name="run_tests",
        allowed_role=AgentRole.TESTING,
        status=status,
        input_summary=f"component={component}",
        output_summary="1 passed" if status is ToolStatus.SUCCESS else "1 failed",
        duration_ms=1,
        evidence_reference=f"mcp://quality/run_tests#{component}",
    )


# The order that matters: the failure is not last.
_MIXED = [
    _component_result("api-gateway", ToolStatus.SUCCESS),
    _component_result("ai-service", ToolStatus.FAIL),
    _component_result("frontend", ToolStatus.SUCCESS),
]


def _state(results: list[ToolResult]) -> EngineeringState:
    return EngineeringState(
        run_id="multi", requirement="change the gateway", tool_results=results
    )


def test_testing_reports_failure_when_any_component_failed() -> None:
    envelope = build_context(AgentRole.TESTING, _state(_MIXED), "test")
    result = TestingAgent().execute(envelope)

    assert result.status is ToolStatus.FAIL, (
        "a passing component that ran last hid a failing one"
    )


def test_the_failing_component_is_named() -> None:
    """An aggregate verdict that cannot say which component failed is not actionable."""
    envelope = build_context(AgentRole.TESTING, _state(_MIXED), "test")
    result = TestingAgent().execute(envelope)

    assert any("ai-service" in failure for failure in result.failures), result.failures


def test_a_passing_component_is_not_reported_as_failing() -> None:
    envelope = build_context(AgentRole.TESTING, _state(_MIXED), "test")
    result = TestingAgent().execute(envelope)

    joined = " ".join(result.failures)
    assert "api-gateway" not in joined
    assert "frontend" not in joined


def test_every_component_result_is_reported_not_only_the_last() -> None:
    envelope = build_context(AgentRole.TESTING, _state(_MIXED), "test")
    result = TestingAgent().execute(envelope)

    assert len(result.actual_results) == 3, result.actual_results


def test_the_reviewer_rejects_when_an_earlier_component_failed() -> None:
    envelope = build_context(AgentRole.REVIEWER, _state(_MIXED), "review")
    decision = ReviewerAgent().execute(envelope)

    assert decision.status is not ReviewerStatus.APPROVED
    assert any("run_tests" in problem for problem in decision.problems), decision.problems


def test_all_components_green_still_passes_the_gate() -> None:
    """The fix must not turn every multi-component run into a rejection."""
    green = [
        _component_result("api-gateway", ToolStatus.SUCCESS),
        _component_result("ai-service", ToolStatus.SUCCESS),
    ]
    result = TestingAgent().execute(
        build_context(AgentRole.TESTING, _state(green), "test")
    )
    assert result.status is ToolStatus.SUCCESS
    assert not [f for f in result.failures if "run_tests" in f]


# -- the other half: results have to say which component they came from --------


def test_quality_results_are_anonymous_until_a_component_is_named(tmp_path) -> None:
    """Today's default is unchanged, so a single-component run behaves as before."""
    from engineering_team.mcp.quality import QualityMCP

    result = QualityMCP(tmp_path).run_tests(AgentRole.DEVELOPER)  # denied role
    assert result.evidence_reference is None


def test_a_named_component_stamps_every_result_it_produces(tmp_path) -> None:
    """Without this the grouping collapses ten components into one bucket."""
    from engineering_team.mcp.quality import QualityMCP

    quality = QualityMCP(tmp_path, component="ai-service")
    denied = quality.run_tests(AgentRole.DEVELOPER)
    assert denied.evidence_reference == "mcp://quality/run_tests#ai-service"


def test_two_components_do_not_share_a_bucket(tmp_path) -> None:
    from engineering_team.mcp.quality import QualityMCP

    first = QualityMCP(tmp_path, component="api-gateway").run_tests(AgentRole.DEVELOPER)
    second = QualityMCP(tmp_path, component="ai-service").run_tests(AgentRole.DEVELOPER)
    assert first.evidence_reference != second.evidence_reference
