"""Pure deterministic graph routing functions."""

import hashlib
import re

from engineering_team.contracts.enums import (
    AgentRole,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecuritySeverity,
    ToolStatus,
)
from engineering_team.contracts.models import BASELINE_RISK_PREFIX, ReviewerDecision, ToolResult
from engineering_team.contracts.state import EngineeringState

_ALLOWED_REJECTED_TARGETS = {RouteTarget.ARCHITECTURE, RouteTarget.DEVELOPER}
_HEX = re.compile(r"0x[0-9a-f]+")
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
_WHITESPACE = re.compile(r"\s+")


def _failure_class_text(text: str) -> str:
    """Text with the parts that change between two identical failures removed.

    Runners print progress percentages, durations, timestamps and counts that
    differ between cycles failing for the same reason.
    """
    folded = _HEX.sub("#", text.casefold())
    return _WHITESPACE.sub(" ", _NUMBER.sub("#", folded)).strip()


def remediation_fingerprint(decision: ReviewerDecision) -> str:
    """Identity of a rejected outcome's failure class, not of its wording.

    Hashing raw text made every cycle look new: in flaskapiproduct-dry-20260916j
    five rejections gave one reason and five fingerprints. Residual baseline risk
    is not caused by the change, so it cannot tell two attempts apart.
    """
    problems = sorted({
        _failure_class_text(problem)
        for problem in decision.problems
        if not problem.startswith(BASELINE_RISK_PREFIX)
    })
    material = "\n".join([
        decision.remediation_category.value if decision.remediation_category else "none",
        _failure_class_text(decision.reason),
        *problems,
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def failure_repetitions(fingerprints: list[str]) -> int:
    """How many times the latest failure class has occurred anywhere in this run.

    A trailing streak missed an A-B-A loop: spring-demo-dry-20260916e alternated
    two fingerprints for five cycles and was never stopped early.
    """
    if not fingerprints:
        return 0
    return fingerprints.count(fingerprints[-1])


def applied_diff_fingerprint(tool_results: list[ToolResult]) -> str:
    """Identity of the code a cycle left in the workspace; empty when unknown.

    get_diff is cumulative, so its latest successful Developer result describes the
    whole change the Reviewer just rejected.
    """
    latest = next(
        (
            item
            for item in reversed(tool_results)
            if item.tool_name == "get_diff"
            and item.allowed_role is AgentRole.DEVELOPER
            and item.status is ToolStatus.SUCCESS
        ),
        None,
    )
    if latest is None or not latest.output_summary.strip():
        return ""
    return hashlib.sha256(latest.output_summary.encode("utf-8")).hexdigest()[:20]


def code_unchanged_since_earlier_rejection(fingerprints: list[str]) -> bool:
    """Whether the latest rejected cycle left exactly the code an earlier one did.

    Retrying code that did not change cannot change the outcome.
    """
    if not fingerprints or not fingerprints[-1]:
        return False
    return fingerprints[-1] in fingerprints[:-1]


def rejection_record(
    state: EngineeringState, decision: ReviewerDecision
) -> dict[str, list[str]]:
    """What a rejection appends to the run's memory of its failures."""
    return {
        "failure_fingerprints": [
            *state.failure_fingerprints, remediation_fingerprint(decision)
        ],
        "applied_diff_fingerprints": [
            *state.applied_diff_fingerprints, applied_diff_fingerprint(state.tool_results)
        ],
    }


def review_route(
    decision: ReviewerDecision,
    iteration: int,
    *,
    max_iterations: int = 3,
    repeated_failures: int = 1,
    unchanged_code: bool = False,
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
    if unchanged_code and repeated_failures >= 2:
        return "HUMAN_REVIEW_REQUIRED"
    if repeated_failures >= 3:
        return "HUMAN_REVIEW_REQUIRED"
    return decision.return_to.value


def security_route(severity: SecuritySeverity) -> str:
    return "security_hitl" if severity is SecuritySeverity.CRITICAL else "Testing"
