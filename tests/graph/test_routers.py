from engineering_team.contracts.enums import (
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecuritySeverity,
)
from engineering_team.contracts.models import ReviewerDecision
from engineering_team.graph.routers import (
    failure_repetitions,
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
