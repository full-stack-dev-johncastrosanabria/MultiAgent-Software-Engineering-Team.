"""Pure deterministic graph routing functions."""

import hashlib
import re

from engineering_team.contracts.enums import (
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecuritySeverity,
)
from engineering_team.contracts.models import ReviewerDecision

_ALLOWED_REJECTED_TARGETS = {RouteTarget.ARCHITECTURE, RouteTarget.DEVELOPER}


def remediation_fingerprint(decision: ReviewerDecision) -> str:
    """Stable identity for one rejected outcome, without retaining diagnostics."""
    material = "\n".join([
        decision.remediation_category.value if decision.remediation_category else "none",
        decision.reason,
        *decision.problems,
    ]).casefold()
    normalized = re.sub(r"\s+", " ", material).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def trailing_failure_repetitions(fingerprints: list[str]) -> int:
    if not fingerprints:
        return 0
    latest = fingerprints[-1]
    count = 0
    for fingerprint in reversed(fingerprints):
        if fingerprint != latest:
            break
        count += 1
    return count


def review_route(
    decision: ReviewerDecision,
    iteration: int,
    *,
    max_iterations: int = 3,
    repeated_failures: int = 1,
) -> str:
    if decision.status is ReviewerStatus.APPROVED:
        return "FinalReport"
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    if iteration >= max_iterations:
        return "HUMAN_REVIEW_REQUIRED"
    if decision.return_to not in _ALLOWED_REJECTED_TARGETS:
        return "HUMAN_REVIEW_REQUIRED"
    expected = (
        RouteTarget.ARCHITECTURE
        if decision.remediation_category is RemediationCategory.ARCHITECTURE
        else RouteTarget.DEVELOPER
    )
    if decision.remediation_category is None or decision.return_to is not expected:
        return "HUMAN_REVIEW_REQUIRED"
    if repeated_failures >= 3:
        return "HUMAN_REVIEW_REQUIRED"
    if repeated_failures == 2 and expected is RouteTarget.DEVELOPER:
        return "Architecture"
    return decision.return_to.value


def security_route(severity: SecuritySeverity) -> str:
    return "security_hitl" if severity is SecuritySeverity.CRITICAL else "Testing"
