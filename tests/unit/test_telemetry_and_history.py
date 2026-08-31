"""Findings 5 and 6: telemetry that misreports, and history that is rewritten.

Both are the same failure in different places — a record that describes something
other than what happened, which is worse than no record because it is believed.
"""

from __future__ import annotations

import json

import httpx

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.contracts.models import ProductSpecification
from engineering_team.llm.cloud import CloudModelRuntime
from engineering_team.models.context import ContextEnvelope
from engineering_team.run_events import _route_steps


def _envelope() -> ContextEnvelope:
    return ContextEnvelope(
        agent=AgentRole.PRODUCT, current_task="classify requirement",
        state_projection={"requirement": "Add a health endpoint"},
        rag_evidence=[], tool_results=[], remediation_feedback=None,
        output_schema="", allowed_tools=[], model_profile="CLOUD",
        projection_fingerprint="fixture-fingerprint",
    )


def _candidate() -> ProductSpecification:
    return ProductSpecification(
        objective="Add a health endpoint", actors=["operator"],
        business_rules=["Return healthy status"], constraints=["Keep compatibility"],
        acceptance_criteria=["GET health returns 200"], nfrs=["Deterministic"],
        ambiguities=[], assumptions=[], source_requirement="Add a health endpoint",
    )


def _succeeding_runtime(*, primary: bool) -> CloudModelRuntime:
    """A cloud runtime whose provider answers correctly."""
    payload = json.dumps(_candidate().model_dump(mode="json"))

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": payload}]}}]
        })

    settings = Settings(cloud_enabled=True, local_first=False, gemini_api_key="k")
    return CloudModelRuntime(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
        primary=primary,
    )


# -- finding 5: the primary path reported itself as a fallback ---------------


def test_a_cloud_primary_does_not_report_itself_as_a_fallback() -> None:
    """Confirmed live in run-8e101cac: fallback_used=true with reason
    CLOUD_FIRST on the path that was configured as primary. The trace beside it
    already said "primary", so the telemetry contradicted itself."""
    runtime = _succeeding_runtime(primary=True)
    _, info = runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), _candidate())

    assert info.fallback_used is False
    assert info.fallback_reason is None


def test_a_cloud_secondary_still_reports_a_fallback() -> None:
    """The fix must not blind the field it is correcting."""
    runtime = _succeeding_runtime(primary=False)
    _, info = runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), _candidate())

    assert info.fallback_used is True
    assert info.fallback_reason


def test_the_trace_and_the_record_agree() -> None:
    """They disagreed, which is how the finding was noticed at all."""
    for primary in (True, False):
        runtime = _succeeding_runtime(primary=primary)
        _, info = runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), _candidate())
        assert info.fallback_used is not primary


# -- finding 6: past decisions shown with the latest review's numbers --------


def _state(review_reason: str, review_score: float) -> dict[str, object]:
    """Two review cycles: the first rejected, the second approved."""
    return {
        "route_history": [
            "Product", "Architecture", "Developer", "Security", "Testing",
            "Reviewer", "Developer", "Security", "Testing", "Reviewer",
        ],
        "review": {
            "status": "APPROVED", "score": review_score, "reason": review_reason,
            "problems": [], "subscores": {}, "confidence": 1, "return_to": None,
            "evidence_references": [],
        },
        "review_history": [
            {"status": "REJECTED", "score": 40.0,
             "reason": "failed tests require implementation remediation"},
            {"status": "APPROVED", "score": review_score, "reason": review_reason},
        ],
    }


def test_a_rejection_is_not_shown_with_the_approval_that_followed_it() -> None:
    """The first transition sent work back; the report gave it the final
    review's reason and score, so a rejection appeared to have been an 85."""
    steps = _route_steps(_state("all gates satisfied", 85.0), "2026-08-30T00:00:00Z")

    rejections = [step for step in steps if step["decision"] == "REJECTED"]
    assert rejections, "the run did send work back"
    assert rejections[0]["reason"] != "all gates satisfied"
    assert rejections[0]["score"] != 85.0


def test_the_final_decision_still_carries_the_final_review() -> None:
    steps = _route_steps(_state("all gates satisfied", 85.0), "2026-08-30T00:00:00Z")

    final = steps[-1]
    assert final["reason"] == "all gates satisfied"
    assert final["score"] == 85.0


def test_each_cycle_is_numbered_in_the_order_it_happened() -> None:
    steps = _route_steps(_state("all gates satisfied", 85.0), "2026-08-30T00:00:00Z")
    assert [step["iteration"] for step in steps] == sorted(
        step["iteration"] for step in steps
    )
