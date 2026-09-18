from engineering_team.contracts.enums import (
    AgentRole,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecuritySeverity,
    ToolStatus,
)
from engineering_team.contracts.models import ReviewerDecision, ToolResult
from engineering_team.contracts.state import EngineeringState
from engineering_team.graph.routers import (
    applied_diff_fingerprint,
    code_unchanged_since_earlier_rejection,
    failure_repetitions,
    rejection_record,
    remediation_fingerprint,
    review_route,
    security_route,
)


def test_rejected_decision_routes_to_remediation_and_increments_cycle() -> None:
    decision = ReviewerDecision(
        status=ReviewerStatus.REJECTED,
        score=40,
        subscores={},
        reason="fix",
        remediation_category=RemediationCategory.IMPLEMENTATION,
        return_to=RouteTarget.DEVELOPER,
        confidence=0.9,
    )
    assert review_route(decision, iteration=0) == "Developer"


def test_third_failed_cycle_requires_human_review() -> None:
    decision = ReviewerDecision(
        status=ReviewerStatus.REJECTED,
        score=40,
        subscores={},
        reason="fix",
        remediation_category=RemediationCategory.IMPLEMENTATION,
        return_to=RouteTarget.DEVELOPER,
        confidence=0.9,
    )
    assert review_route(decision, iteration=3, max_iterations=3) == "HUMAN_REVIEW_REQUIRED"


def test_a_repeated_failure_keeps_its_route_and_stops_at_its_third_occurrence() -> None:
    """Sending the second repetition to Architecture re-entered a loop that could
    not change its inputs (audit 2026-09-16, C-02 and C-03)."""
    decision = ReviewerDecision(
        status=ReviewerStatus.REJECTED,
        score=40,
        subscores={},
        reason="same failed assertion",
        remediation_category=RemediationCategory.IMPLEMENTATION,
        return_to=RouteTarget.DEVELOPER,
        confidence=0.9,
    )

    assert review_route(
        decision, iteration=2, max_iterations=5, repeated_failures=2
    ) == "Developer"
    assert review_route(
        decision, iteration=3, max_iterations=5, repeated_failures=3
    ) == "HUMAN_REVIEW_REQUIRED"


def test_critical_security_always_routes_to_hitl() -> None:
    assert security_route(SecuritySeverity.CRITICAL) == "security_hitl"


def _rejection(reason: str, problems: list[str]) -> ReviewerDecision:
    return ReviewerDecision(
        status=ReviewerStatus.REJECTED,
        score=40,
        subscores={},
        problems=problems,
        reason=reason,
        remediation_category=RemediationCategory.TESTING,
        return_to=RouteTarget.DEVELOPER,
        confidence=1,
    )


def test_a_fingerprint_ignores_progress_counts_and_residual_baseline_risk() -> None:
    """flaskapiproduct-dry-20260916j: five rejections gave one reason and five
    fingerprints, because percentages, file counts and scanner tails moved."""
    first = _rejection(
        "failed tests require implementation remediation",
        [
            "Residual baseline dependency risk reported by scanners; CVE-2026-1111",
            "tests/test_products_filter.py::TestProductFilter::test_partial_match FAILED [ 73%]",
            "the design saw 20 of 27 ranked files (26%) in 0.41s",
        ],
    )
    second = _rejection(
        "failed tests require implementation remediation",
        [
            "Residual baseline dependency risk reported by scanners; CVE-2026-2222 GHSA-x",
            "tests/test_products_filter.py::TestProductFilter::test_partial_match FAILED [ 76%]",
            "the design saw 60 of 67 ranked files (10%) in 1.07s",
        ],
    )

    assert remediation_fingerprint(first) == remediation_fingerprint(second)


def test_a_fingerprint_changes_when_a_different_test_fails() -> None:
    partial = _rejection(
        "failed tests require implementation remediation",
        ["tests/test_products_filter.py::TestProductFilter::test_partial_match FAILED"],
    )
    missing_q = _rejection(
        "failed tests require implementation remediation",
        ["tests/test_products_filter.py::TestProductFilter::test_without_q_parameter FAILED"],
    )

    assert remediation_fingerprint(partial) != remediation_fingerprint(missing_q)


def test_repetitions_count_the_whole_run_not_a_trailing_streak() -> None:
    """spring-demo-dry-20260916e alternated two failures for five cycles."""
    assert failure_repetitions([]) == 0
    assert failure_repetitions(["a", "b", "a"]) == 2
    assert failure_repetitions(["a", "b", "a", "b", "a"]) == 3


def _diff(output: str, status: ToolStatus = ToolStatus.SUCCESS) -> ToolResult:
    return ToolResult(
        tool_name="get_diff",
        allowed_role=AgentRole.DEVELOPER,
        status=status,
        input_summary="git diff",
        output_summary=output,
        duration_ms=1,
    )


def test_the_applied_diff_fingerprint_describes_the_latest_successful_diff() -> None:
    early = _diff("--- a/x\n+++ b/x\n+one")
    late = _diff("--- a/x\n+++ b/x\n+two")

    assert applied_diff_fingerprint([early, late]) == applied_diff_fingerprint([late])
    assert applied_diff_fingerprint([early, late]) != applied_diff_fingerprint([early])
    assert applied_diff_fingerprint([]) == ""
    assert applied_diff_fingerprint([_diff("   ")]) == ""
    assert applied_diff_fingerprint([_diff("+x", ToolStatus.FAIL)]) == ""


def test_unchanged_code_is_claimed_only_when_an_earlier_rejection_left_the_same_diff() -> None:
    assert code_unchanged_since_earlier_rejection(["d1", "d2", "d1"]) is True
    assert code_unchanged_since_earlier_rejection(["d1", "d2"]) is False
    assert code_unchanged_since_earlier_rejection(["", ""]) is False
    assert code_unchanged_since_earlier_rejection([]) is False


def test_the_same_code_failing_the_same_way_twice_stops_the_loop() -> None:
    """spring-demo-dry-20260916e left an identical diff and compile error five times."""
    decision = _rejection(
        "failed tests require implementation remediation",
        ["package org.springframework.boot.test.autoconfigure.web.servlet does not exist"],
    )

    assert review_route(
        decision, iteration=2, max_iterations=5, repeated_failures=2, unchanged_code=True
    ) == "HUMAN_REVIEW_REQUIRED"
    assert review_route(
        decision, iteration=2, max_iterations=5, repeated_failures=1, unchanged_code=True
    ) == "Developer"


def test_a_rejection_records_its_failure_class_and_the_code_it_rejected() -> None:
    state = EngineeringState(
        run_id="r",
        requirement="filter products by q",
        failure_fingerprints=["f0"],
        applied_diff_fingerprints=["d0"],
        tool_results=[_diff("--- a/app.py\n+++ b/app.py\n+new")],
    )
    decision = _rejection("failed tests require implementation remediation", ["assert 5 == 1"])

    record = rejection_record(state, decision)

    assert record["failure_fingerprints"] == ["f0", remediation_fingerprint(decision)]
    assert record["applied_diff_fingerprints"] == [
        "d0", applied_diff_fingerprint(state.tool_results)
    ]
