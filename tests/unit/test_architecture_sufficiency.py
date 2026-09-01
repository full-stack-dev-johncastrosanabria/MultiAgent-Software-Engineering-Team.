"""Architecture must be able to say it did not see enough, and be believed.

The stage reads a bounded slice of a repository. When that slice is a small part
of the whole, a proposal built on it is a guess, and a run that treats it as a
design sends the Developer to implement against interfaces nobody verified —
which is the loop finding 8 describes.

The signal is computed by the graph, not confessed by the model. A routing
decision must not depend on free text, and an agent that overlooked something is
the last thing that can be trusted to report it.
"""

from __future__ import annotations

from engineering_team.contracts.enums import (
    AgentRole,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    ToolStatus,
)
from engineering_team.contracts.models import (
    ArchitectureProposal,
    SecurityReview,
    TestResult,
    ToolResult,
)
from engineering_team.contracts.state import EngineeringState
from engineering_team.models.context import build_context
from engineering_team.repository_evidence import assess_evidence_sufficiency


def _proposal(**overrides) -> ArchitectureProposal:
    base = {
        "components": ["service"], "apis": [], "data_changes": [],
        "integrations": [], "dependencies": [], "decisions": ["keep the boundary"],
        "risks": ["drift"], "impact": "bounded",
        "evidence_references": ["mcp://repository/read_file#a.py"],
    }
    base.update(overrides)
    return ArchitectureProposal(**base)


def test_a_proposal_can_record_that_its_evidence_was_incomplete() -> None:
    proposal = _proposal(evidence_sufficient=False, evidence_gap="20 of 24 files unread")
    assert proposal.evidence_sufficient is False
    assert "20 of 24" in proposal.evidence_gap


def test_saying_nothing_is_distinct_from_saying_it_was_enough() -> None:
    """Finding 1's lesson: silence must not read as a clean bill of health."""
    assert _proposal().evidence_sufficient is None


def test_the_graph_computes_sufficiency_rather_than_trusting_the_model() -> None:
    """An agent that overlooked something cannot be the one to report it."""
    from engineering_team.repository_evidence import assess_evidence_sufficiency

    enough = assess_evidence_sufficiency(read=20, ranked=22, omitted=0)
    assert enough.sufficient is True

    thin = assess_evidence_sufficiency(read=4, ranked=400, omitted=396)
    assert thin.sufficient is False
    assert "396" in thin.gap


def test_a_model_claiming_sufficiency_cannot_override_the_count() -> None:
    from engineering_team.repository_evidence import assess_evidence_sufficiency

    thin = assess_evidence_sufficiency(read=1, ranked=200, omitted=199)
    assert thin.sufficient is False


def test_a_repository_smaller_than_the_budget_is_always_sufficient() -> None:
    """Reading everything there is cannot be insufficient."""
    from engineering_team.repository_evidence import assess_evidence_sufficiency

    assert assess_evidence_sufficiency(read=3, ranked=3, omitted=0).sufficient is True


def test_task_boundary_coverage_beats_generic_search_hit_coverage() -> None:
    result = assess_evidence_sufficiency(
        read=7,
        ranked=27,
        omitted=20,
        required_paths={
            "tests/test_products.py",
            "app/routes/products.py",
            "app/models/product.py",
        },
        visible_paths={
            "tests/test_products.py",
            "app/routes/products.py",
            "app/models/product.py",
        },
    )

    assert result.sufficient is True


def test_missing_task_boundary_is_reported_as_insufficient() -> None:
    result = assess_evidence_sufficiency(
        read=7,
        ranked=27,
        omitted=20,
        required_paths={
            "tests/test_products.py",
            "app/routes/products.py",
            "app/models/product.py",
        },
        visible_paths={
            "tests/test_products.py",
            "app/routes/products.py",
        },
    )

    assert result.sufficient is False
    assert "app/models/product.py" in result.gap


# -- the Reviewer stops sending every failure to the Developer ---------------


def _state(*, sufficient: bool | None, failing: bool) -> EngineeringState:
    return EngineeringState(
        run_id="r1", requirement="add password recovery",
        architecture=_proposal(
            evidence_sufficient=sufficient,
            evidence_gap="" if sufficient is not False else "396 ranked files unread",
        ),
        security_review=SecurityReview(
            status="PASS", highest_severity="LOW", findings=[],
            recommendations=[], sources=[],
            checklist={"authentication": "PASS", "authorization": "PASS", "input_validation": "PASS", "sensitive_information": "PASS", "secrets": "PASS", "injection": "PASS", "access_control": "PASS", "idor": "PASS", "logging": "PASS", "data_protection": "PASS", "api_abuse": "PASS", "rate_limiting": "PASS", "owasp": "PASS"},
            requires_hitl=False,
        ),
        test_results=[TestResult(
            proposed_tests=["happy_path"], generated_tests=[],
            executed_tests=["run_tests"],
            actual_results=["1 failed" if failing else "1 passed"],
            status=ToolStatus.FAIL if failing else ToolStatus.SUCCESS,
            failures=["AttributeError: module has no attribute 'recuperar'"] if failing else [],
            coverage_mapping={"happy_path": ["run_tests"]},
            evidence_references=["run_tests"],
        )],
        tool_results=[ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING,
            status=ToolStatus.FAIL if failing else ToolStatus.SUCCESS,
            input_summary="pytest", output_summary="1 failed" if failing else "1 passed",
            duration_ms=1,
        )],
    )


def _decide(state: EngineeringState):
    from engineering_team.agents.reviewer import ReviewerAgent

    return ReviewerAgent().execute(build_context(AgentRole.REVIEWER, state, "review"))


def test_a_failure_on_admittedly_thin_evidence_goes_back_to_architecture() -> None:
    """Asking the Developer to fix code against a design built on 1% of the
    repository is what produced the loop: the same four files, the same
    interfaces, the same failure."""
    decision = _decide(_state(sufficient=False, failing=True))

    assert decision.status is ReviewerStatus.REJECTED
    assert decision.remediation_category is RemediationCategory.ARCHITECTURE
    assert decision.return_to is RouteTarget.ARCHITECTURE


def test_a_failure_on_complete_evidence_still_goes_to_the_developer() -> None:
    """The fix must not send everything to Architecture instead."""
    decision = _decide(_state(sufficient=True, failing=True))

    assert decision.remediation_category is RemediationCategory.TESTING
    assert decision.return_to is RouteTarget.DEVELOPER


def test_thin_evidence_alone_does_not_reject_a_passing_run() -> None:
    """Incomplete reading is a reason to distrust a failure, not to invent one."""
    decision = _decide(_state(sufficient=False, failing=False))
    assert decision.remediation_category is not RemediationCategory.ARCHITECTURE
