"""Pure deterministic graph routing functions."""

import hashlib
import re

from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    ErrorCode,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecuritySeverity,
    StopCause,
    ToolStatus,
)
from engineering_team.contracts.models import (
    BASELINE_RISK_PREFIX,
    ModelExecutionInfo,
    ReviewerDecision,
    ToolResult,
)
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


def remediation_target_is_consistent(decision: ReviewerDecision) -> bool:
    """Whether a rejection names a remediation route this graph is willing to take.

    Shared with `classify_stop_cause` rather than restated there: both have to
    agree on which rejections stop the run before stagnation is ever considered,
    and a second copy of this rule would drift from the routing it describes.
    """
    if decision.return_to not in _ALLOWED_REJECTED_TARGETS:
        return False
    expected = (
        RouteTarget.ARCHITECTURE
        if decision.remediation_category is RemediationCategory.ARCHITECTURE
        else RouteTarget.DEVELOPER
    )
    return decision.remediation_category is not None and decision.return_to is expected


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
    if not remediation_target_is_consistent(decision):
        return "HUMAN_REVIEW_REQUIRED"
    if unchanged_code and repeated_failures >= 2:
        return "HUMAN_REVIEW_REQUIRED"
    if repeated_failures >= 3:
        return "HUMAN_REVIEW_REQUIRED"
    return decision.return_to.value


def security_route(severity: SecuritySeverity) -> str:
    return "security_hitl" if severity is SecuritySeverity.CRITICAL else "Testing"


_WRITE_TOOLS = frozenset({"create_file", "update_file"})

_CHAIN_EXHAUSTION_CODES = frozenset({
    ErrorCode.CLOUD_FALLBACK_UNAVAILABLE,
    ErrorCode.LLM_AVAILABILITY_ERROR,
    ErrorCode.AGENT_TIMEOUT,
})
"""The codes a run ends with once no model in its chain produced an artifact.

Grouped because which of the three lands last depends on how the chain is
ordered, not on what went wrong: under `cloud_first` the same cloud refusal that
would be recorded as `CLOUD_FALLBACK_UNAVAILABLE` arrives as
`LLM_AVAILABILITY_ERROR` instead.
"""

_CONTENT_REJECTION_CATEGORIES = frozenset({
    "governed_contradiction",
    "ineffective_remediation",
    "incomplete_output",
    "schema_validation",
})
"""`ModelExecutionInfo.error_category` values that mean the answer was refused.

The provider replied and this system rejected what it said. The graph cannot
tell these apart from an outage by error code alone: `cloud.py` raises every one
of them as `CLOUD_FALLBACK_UNAVAILABLE`, so the only typed record of what really
happened is the category the runtime stamped on the attempt.
"""


def _stagnated(state: EngineeringState) -> bool:
    """The two stagnation conditions `review_route` uses, read back from state."""
    repeated = failure_repetitions(state.failure_fingerprints)
    return repeated >= 3 or (
        code_unchanged_since_earlier_rejection(state.applied_diff_fingerprints)
        and repeated >= 2
    )


def _generations_of_the_final_failure(state: EngineeringState) -> list[ModelExecutionInfo]:
    """Every model attempt belonging to the failure that ended the run.

    That is the trailing run of failed attempts: the moment a stage produced an
    artifact it recorded an attempt with no error, so everything after the last
    such attempt was tried, and failed, on the way to this stop. Scoping it this
    way keeps a rejection that a later retry recovered from out of the verdict,
    and keeps every link of the exhausted chain inside it.
    """
    tail: list[ModelExecutionInfo] = []
    for info in reversed(state.model_usage):
        if not info.error:
            break
        tail.append(info)
    tail.reverse()
    return tail


def _content_was_rejected(state: EngineeringState) -> bool:
    """Whether any link of the failed chain answered and had its answer refused.

    Reading only the newest attempt was not enough, for a structural reason:
    under `cloud_first` the cloud is the *primary* runtime and the local model
    the secondary, so a cloud refusal is recorded first and an ordinary local
    outage lands on top of it. Which runtime happens to record last is a
    configuration accident; whether any link refused what we asked it to write
    is not. So the question is put to the whole failure.

    `governed_fields_diff` and `violated_rule` are only ever set on a governed
    contradiction, so their presence is proof on its own; `error_category`
    covers the truncated and schema-invalid generations, which name no field.
    """
    return any(
        info.governed_fields_diff is not None
        or info.violated_rule is not None
        or info.error_category in _CONTENT_REJECTION_CATEGORIES
        for info in _generations_of_the_final_failure(state)
    )



def _write_attempt_failed(state: EngineeringState) -> bool:
    """Whether a write tool ran and did not succeed."""
    return any(
        item.tool_name in _WRITE_TOOLS and item.status is not ToolStatus.SUCCESS
        for item in state.tool_results
    )


def _authored_changes_were_never_written(state: EngineeringState) -> bool:
    """Whether the run holds applied file contents no write tool ever saw.

    The destructive-change guardrail refuses before the write loop, so it is the
    one stop that ends with an APPLIED implementation and no write evidence at
    all. It and a failed write share `ErrorCode.TOOL_ERROR`, and the tool record
    is the only typed thing that separates them.
    """
    implementation = state.implementation
    return (
        implementation is not None
        and implementation.action_mode is ActionMode.APPLIED
        and bool(implementation.file_contents)
        and not any(item.tool_name in _WRITE_TOOLS for item in state.tool_results)
    )


def classify_stop_cause(state: EngineeringState, *, max_iterations: int) -> StopCause:
    """Name why this run stopped, from the typed evidence the graph already has.

    Called once, from `human_node`, after the graph has decided to stop. It never
    re-decides: where `review_route` made the call it is read back in that same
    order, and everywhere else the stopping node's own `WorkflowError` says so.
    Reconstructing this afterwards from error prose is what made the audit report
    refused answers as provider outages.

    `max_iterations` is a parameter rather than a state field because the
    remediation budget is configuration, not evidence: it belongs to
    `build_engineering_graph`, inside whose closure `human_node` already has it.
    """
    if not state.human_review_required:
        # No node recorded a failure, so the stop came from the routers.
        if state.review is None:
            # `security_hitl`: the Reviewer never ran, so `review_route` never
            # decided anything. A critical security finding has no word in this
            # vocabulary yet, and borrowing one would be worse than saying so.
            return StopCause.UNKNOWN
        if state.review.status is ReviewerStatus.APPROVED:
            return StopCause.APPROVED
        # From here on the order is `review_route`'s own, because a run that met
        # several of these conditions was stopped by the first one it met.
        if state.iteration >= max_iterations:
            return StopCause.ITERATION_LIMIT
        if not remediation_target_is_consistent(state.review):
            # `review_route` stops on a self-contradicting rejection *before* it
            # looks at stagnation. Reading stagnation first would report a run
            # that was never given a remediation route as one that spun.
            return StopCause.UNKNOWN
        if _stagnated(state):
            return StopCause.STAGNATION
        return StopCause.UNKNOWN
    if not state.errors:
        # Every path that raises the flag appends a `WorkflowError` first, so an
        # empty list means an unrecorded one -- surfaced, not guessed at.
        return StopCause.UNKNOWN
    last = state.errors[-1]
    if last.code is ErrorCode.INFRASTRUCTURE_ERROR:
        return StopCause.INFRASTRUCTURE_UNAVAILABLE
    if last.code is ErrorCode.MCP_ERROR:
        return StopCause.MCP_UNAVAILABLE
    if last.code is ErrorCode.TOOL_ERROR:
        if _authored_changes_were_never_written(state):
            return StopCause.DESTRUCTIVE_AUTHORIZATION_BLOCKED
        if _write_attempt_failed(state):
            return StopCause.WRITE_FAILED
        return StopCause.UNKNOWN
    if last.code is ErrorCode.LLM_QUALITY_ERROR:
        return StopCause.LLM_QUALITY_REJECTED
    if last.code in _CHAIN_EXHAUSTION_CODES:
        # None of these three codes says why the chain was entered, and the last
        # one recorded is only the last link to fail. A refusal anywhere in the
        # chain outranks them: the provider answered and this system rejected
        # what it said, which is a different run to repair than an outage. The
        # misclassification runs deeper than it looks -- `cloud.py` raises a
        # governed contradiction as `CLOUD_FALLBACK_UNAVAILABLE`, and the graph
        # classifies that message by prefix, so under `cloud_first` a refusal by
        # the primary cloud model is recorded as `LLM_AVAILABILITY_ERROR`.
        if _content_was_rejected(state):
            return StopCause.LLM_QUALITY_REJECTED
        # Second signal, and only meaningful on this code: the graph copies the
        # primary failure's retryability onto the fallback error, and only a
        # quality failure is unretryable. The other two are always recorded
        # retryable, so reading it there would prove nothing.
        if last.code is ErrorCode.CLOUD_FALLBACK_UNAVAILABLE and not last.retryable:
            return StopCause.LLM_QUALITY_REJECTED
        return StopCause.PROVIDER_CHAIN_EXHAUSTED
    return StopCause.UNKNOWN
