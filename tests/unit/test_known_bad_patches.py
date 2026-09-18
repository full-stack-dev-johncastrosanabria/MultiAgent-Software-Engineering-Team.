"""Task 8 -- calibrating acceptance (C-04, M-22): a battery of five known-bad
patches the Reviewer's evidence gate is supposed to refuse, measured rather
than fixed. Source: research-replay.md Sec.7 and
docs/audit160926/12-plan-de-remediacion.md row 6.

This module does not repair anything. Each bad patch below is built, run
through the real deterministic agents (never a mock of the gate itself), and
the resulting decision is asserted. Where the Reviewer already rejects the
patch, the test is an ordinary passing characterisation. Where it does not,
the test is `xfail(strict=True)`, so the day phase 2 changes the gate the
suite reports an XPASS instead of staying silently green.

Bad patch 1 -- a diff that deletes or edits an original, protected test -- is
deliberately NOT reproduced here. Two premise checks (P1, P2) confirmed the
guard and its coverage already exist one layer before the Reviewer:

  * `contracts/developer_plan.py:106-131` (`validate_target_plan`) raises
    ValueError("target plan attempts to modify original tests") the moment a
    proposed `edit_paths` or `new_files` entry names a path in
    `protected_test_paths` -- deleting a protected test and editing one reach
    the exact same guard, because this contract has no delete operation
    distinct from an edit.
  * `tests/unit/test_developer_target_plan.py` already exercises this guard at
    both the unit level (`test_untrusted_plan_cannot_choose_arbitrary_or_
    original_test_edits`, `test_an_original_test_reproposed_as_new_is_still_
    refused`) and the full graph level (`test_invalid_plan_blocks_authoring_
    and_all_writes`, which shows the Developer's own target-plan validator
    blocks the whole plan and the ReviewerAgent is never even invoked -- one
    LLM call happens, not two).

Task 7's replay fixtures (`tests/fixtures/replay/`) do not carry developer
target plans or file inventories, only specifications and reviewer decisions,
so replaying them here would not add real evidence beyond what the two files
above already assert with synthetic paths. Reusing task 7's fixture loader
just to restate an already-covered guard with different literal strings would
be the duplication the task brief asks not to create; the report for this
task cites the existing tests as the evidence for bad patch 1 instead.

Fix round 1 (task review, two Important findings): the Testing-then-Reviewer
chain bad patch 5 needs is Task 7's own `_run_testing_then_review`
(`tests/unit/test_lexical_coverage_gate.py`), moved to
`tests/_replay.py::run_testing_then_review` and imported from both files rather
than kept as a second copy under a different name; and bad patch 5's
happy-path-only specification was checked against all four real frozen
specs and confirmed to match none of them (every one requires `boundary`, and
three of four also `business_rule`/`validation`) -- a second, realistic-spec
variant of bad patch 5 is added below, replayed directly against trace
`d29547c7b7`, rather than leaving that comparison as a report-only claim.
"""

from __future__ import annotations

import pytest
from _replay import load_trace, run_testing_then_review

from engineering_team.agents.reviewer import ReviewerAgent
from engineering_team.agents.security import SecurityAgent
from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecurityStatus,
    ToolStatus,
)
from engineering_team.contracts.models import (
    ExecutedTestCase,
    ImplementationResult,
    ProductSpecification,
    ReviewerDecision,
    ToolResult,
)
from engineering_team.contracts.models import TestResult as ContractTestResult
from engineering_team.contracts.state import EngineeringState
from engineering_team.graph.routers import remediation_target_is_consistent, review_route
from engineering_team.models.context import build_context

# -----------------------------------------------------------------------------
# Bad patch 2 -- fixes the reported symptom, reintroduces a baseline regression.
# -----------------------------------------------------------------------------

_REGRESSION_OUTPUT = (
    "=================================== FAILURES ===================================\n"
    "FAILED tests/test_accounts.py::test_negative_balance_is_rejected - assert 200 == 400\n"
    "=========================== short test summary info ============================\n"
    "1 failed, 1 passed in 0.10s\n"
)


def _regression_state(*, baseline: list[str]) -> EngineeringState:
    """A 'fix' that resolves the reported crash but breaks a test that passed
    before this change -- exactly what `classify_failures` (testing_evidence.py)
    exists to tell apart from a test that never worked."""
    return EngineeringState(
        run_id="battery-2-regression",
        requirement="fix the reported crash without breaking existing behaviour",
        baseline_tests=baseline,
        test_results=[ContractTestResult(
            proposed_tests=["happy_path"], generated_tests=[],
            executed_tests=["run_tests"], actual_results=[_REGRESSION_OUTPUT],
            status=ToolStatus.FAIL, failures=[_REGRESSION_OUTPUT],
            coverage_mapping={"happy_path": ["run_tests"]},
            evidence_references=["run_tests"],
        )],
        tool_results=[ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING,
            status=ToolStatus.FAIL, input_summary="pytest",
            output_summary=_REGRESSION_OUTPUT, duration_ms=1,
        )],
    )


def test_bad_patch_2_a_fix_that_reintroduces_a_baseline_regression_is_rejected() -> None:
    """Bad patch 2: the symptom is gone, but a test that passed before this
    change now fails. The Reviewer must send it back to the Developer with the
    regression named, not approve it because *a* fix landed."""
    decision = ReviewerAgent().execute(build_context(
        AgentRole.REVIEWER,
        _regression_state(baseline=["tests/test_accounts.py::test_negative_balance_is_rejected"]),
        "review",
    ))

    assert decision.status is ReviewerStatus.REJECTED
    assert decision.remediation_category is RemediationCategory.TESTING
    assert decision.return_to is RouteTarget.DEVELOPER
    assert any(
        problem.startswith("REGRESSION:")
        and "test_negative_balance_is_rejected" in problem
        for problem in decision.problems
    )


def test_bad_patch_2_control_without_a_recorded_baseline_the_same_failure_is_not_a_regression() -> None:
    """Evidence the assertion above is not vacuous: the same failing state with
    `baseline_tests` cleared still rejects (a failing test remains a failing
    test) but the REGRESSION label disappears, per `classify_failures`'s own
    rule that silence about the past proves nothing broke."""
    decision = ReviewerAgent().execute(build_context(
        AgentRole.REVIEWER, _regression_state(baseline=[]), "review",
    ))

    assert decision.status is ReviewerStatus.REJECTED
    assert not any(problem.startswith("REGRESSION:") for problem in decision.problems)


# -----------------------------------------------------------------------------
# Bad patch 3 -- a preexisting CVE on a dependency manifest this change touched.
# -----------------------------------------------------------------------------

_POM_PATHS = ["order-ms/pom.xml", "order-ms/src/main/java/com/prueba/orderms/domain/Order.java"]


def _touched_manifest_scan_tool() -> ToolResult:
    """The scenario tests/unit/test_security_dependency_scope.py already
    covers at the SecurityAgent level (P5,
    `test_the_same_cves_block_once_the_change_edits_the_manifest`): two CVEs
    that predate this run, reported by a scanner, on a manifest this run's own
    diff modifies. `agents/security.py:101-105` refuses to call that baseline
    risk once the manifest itself was touched."""
    return ToolResult(
        tool_name="run_security_scan", allowed_role=AgentRole.SECURITY,
        status=ToolStatus.FAIL, input_summary="project", duration_ms=1,
        output_summary="CVE-2026-41115 kafka-clients, CVE-2026-75838 swagger-ui",
        scans_dependencies=True, confirmed_dependency_findings=True,
    )


def test_bad_patch_3_a_baseline_cve_on_a_manifest_the_change_touched_is_rejected() -> None:
    """Bad patch 3: this is not only a SecurityAgent classification question --
    the FAIL it produces has to survive the trip through the Reviewer as a real
    rejection, routed back to the Developer, not get lost or downgraded on the
    way. No existing test connects the two; test_security_dependency_scope.py's
    seven tests stop at SecurityAgent's own output."""
    scan_tool = _touched_manifest_scan_tool()
    security_state = EngineeringState(
        run_id="battery-3-scan", requirement="Reject nonpositive quantity",
        tool_results=[scan_tool],
        implementation=ImplementationResult(
            action_mode=ActionMode.APPLIED, changed_files=_POM_PATHS,
            diff="allowlist-only order changes",
            evidence=["mcp://repository/update_file"],
            validation_result="compile ok", security_surface_changed=False,
        ),
    )
    security = SecurityAgent().execute(build_context(AgentRole.SECURITY, security_state, "scan"))
    assert security.status is SecurityStatus.FAIL, "P5's own guarantee: this must not become baseline risk"

    review_state = EngineeringState(
        run_id="battery-3-review", requirement="Reject nonpositive quantity",
        security_review=security, tool_results=[scan_tool],
    )
    decision = ReviewerAgent().execute(build_context(AgentRole.REVIEWER, review_state, "review"))

    assert decision.status is ReviewerStatus.REJECTED
    assert decision.remediation_category is RemediationCategory.SECURITY
    assert decision.return_to is RouteTarget.DEVELOPER
    assert any("CVE-2026-41115" in problem for problem in decision.problems), (
        "the specific CVE evidence must reach the Reviewer's problems, not just a generic label"
    )


def test_bad_patch_3_control_the_same_cves_on_an_untouched_manifest_are_baseline_and_approved() -> None:
    """Evidence the rejection above turns on the touched manifest, not on the
    CVEs existing at all: the identical scan, with `changed_files` naming only
    application code (no manifest), is baseline risk and does not block."""
    scan_tool = _touched_manifest_scan_tool()
    security_state = EngineeringState(
        run_id="battery-3-control-scan", requirement="Reject nonpositive quantity",
        tool_results=[scan_tool],
        implementation=ImplementationResult(
            action_mode=ActionMode.APPLIED,
            changed_files=[_POM_PATHS[1]],  # domain source only, not pom.xml
            diff="allowlist-only order changes",
            evidence=["mcp://repository/update_file"],
            validation_result="compile ok", security_surface_changed=False,
        ),
    )
    security = SecurityAgent().execute(build_context(AgentRole.SECURITY, security_state, "scan"))
    assert security.status is SecurityStatus.PASS

    review_state = EngineeringState(
        run_id="battery-3-control-review", requirement="Reject nonpositive quantity",
        security_review=security,
        test_results=[ContractTestResult(
            proposed_tests=["happy_path"], generated_tests=[],
            executed_tests=["run_tests"], actual_results=["1 passed"],
            status=ToolStatus.SUCCESS, failures=[],
            coverage_mapping={"happy_path": ["run_tests"]}, evidence_references=["run_tests"],
        )],
        tool_results=[ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING, status=ToolStatus.SUCCESS,
            input_summary="pytest", output_summary="1 passed", duration_ms=1,
            evidence_reference="run_tests",
        )],
    )
    decision = ReviewerAgent().execute(build_context(AgentRole.REVIEWER, review_state, "review"))

    assert decision.status is ReviewerStatus.APPROVED


# -----------------------------------------------------------------------------
# Bad patch 4 -- a decision with incoherent return_to / remediation_category.
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "remediation_category, return_to",
    [
        (RemediationCategory.ARCHITECTURE, RouteTarget.DEVELOPER),
        (RemediationCategory.TESTING, RouteTarget.ARCHITECTURE),
    ],
    ids=["architecture-category-routed-to-developer", "testing-category-routed-to-architecture"],
)
def test_bad_patch_4_an_incoherent_decision_is_refused_by_the_router_not_guessed_at(
    remediation_category: RemediationCategory, return_to: RouteTarget,
) -> None:
    """Bad patch 4 (P4): a rejection whose own `remediation_category` disagrees
    with its own `return_to`. `ReviewerAgent.execute` never produces this --
    every one of its return statements hard-codes the pair together -- so this
    can only reach the graph as a malformed or adversarial decision. The
    component that refuses it is the graph's ROUTER
    (`graph/routers.py:117-154`, `remediation_target_is_consistent` /
    `review_route`), not the Reviewer: nothing in `agents/reviewer.py` checks
    this coherence, because it never needs to given how it builds its own
    decisions. `review_route` does not try to guess which field is
    authoritative; it stops the run for a human instead."""
    decision = ReviewerDecision(
        status=ReviewerStatus.REJECTED, score=40, subscores={}, reason="incoherent remediation",
        remediation_category=remediation_category, return_to=return_to, confidence=0.9,
    )

    assert remediation_target_is_consistent(decision) is False
    assert review_route(decision, iteration=0) == "HUMAN_REVIEW_REQUIRED"


@pytest.mark.parametrize(
    "remediation_category, return_to",
    [
        (RemediationCategory.ARCHITECTURE, RouteTarget.ARCHITECTURE),
        (RemediationCategory.TESTING, RouteTarget.DEVELOPER),
        (RemediationCategory.IMPLEMENTATION, RouteTarget.DEVELOPER),
        (RemediationCategory.SECURITY, RouteTarget.DEVELOPER),
    ],
)
def test_bad_patch_4_control_every_pairing_a_real_reviewer_produces_is_accepted_as_coherent(
    remediation_category: RemediationCategory, return_to: RouteTarget,
) -> None:
    """Evidence the guard above is not vacuous, and not just refusing
    everything: these four pairings are `agents/reviewer.py`'s own hard-coded
    (category, return_to) combinations (verified against the four frozen
    replay traces in tests/fixtures/replay/, none of which is ever incoherent).
    None of them may trip the guard, or every real rejection would stop for a
    human regardless of the actual routing decision."""
    decision = ReviewerDecision(
        status=ReviewerStatus.REJECTED, score=40, subscores={}, reason="fix",
        remediation_category=remediation_category, return_to=return_to, confidence=0.9,
    )

    assert remediation_target_is_consistent(decision) is True
    assert review_route(decision, iteration=0) == return_to.value


# -----------------------------------------------------------------------------
# Bad patch 5 -- an empty/vacuous test that satisfies acceptance.
# -----------------------------------------------------------------------------


def _vacuous_suite_state(*, business_rules: list[str]) -> EngineeringState:
    """A SYNTHETIC specification and a 'passing' suite whose one test asserts
    nothing about the requirement: the entire body is `assert True`. Whether
    this is caught depends only on whether the specification implies a
    coverage dimension besides `happy_path` (agents/testing.py:_MARKERS).

    This spec shape is deliberately thin -- one acceptance criterion, no
    business rules by default -- and it matches none of the four real
    specifications frozen in tests/fixtures/replay/: every one of those
    requires `boundary` beyond happy_path (three of four also `business_rule`
    and `validation`; verified by running TestingAgent's own dimension
    derivation against all four with no tool_results, reading `proposed_
    tests`). The test below is a demonstrated worst case for the happy-
    path-only shape, not an observed one -- `test_bad_patch_5_real_spec_...`
    further down measures the same finding against a real frozen spec.
    """
    specification = ProductSpecification(
        objective="Add a health check endpoint", actors=["client"],
        business_rules=business_rules, constraints=[],
        acceptance_criteria=["a GET request to /health returns 200"],
        nfrs=[], ambiguities=[], assumptions=[],
        source_requirement="Add a health check endpoint",
    )
    tool = ToolResult(
        tool_name="run_tests", allowed_role=AgentRole.TESTING, status=ToolStatus.SUCCESS,
        input_summary="pytest", output_summary="1 passed", duration_ms=5,
        evidence_reference="mcp://quality/run_tests",
        test_cases=[ExecutedTestCase(
            identifier="test_health_ok", report="PASSED", source_excerpt="assert True",
        )],
    )
    return EngineeringState(
        run_id="battery-5-vacuous", requirement=specification.source_requirement,
        specification=specification, tool_results=[tool],
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "task 8 finding (council 2026-09-17), not yet catalogued as a C-xx/M-xx "
        "row in docs/audit160926/: TestingAgent.execute credits `happy_path` "
        "coverage from any SUCCESS ToolResult carrying a non-empty test_cases "
        "list (agents/testing.py:151-158), without reading whether the test's "
        "body actually asserts anything about the requirement. When the "
        "specification implies no coverage dimension beyond happy_path, a "
        "single `assert True` test satisfies every gate in "
        "ReviewerAgent.execute and the run is APPROVED at score 100 with zero "
        "problems. CAVEAT (added in fix round 1): the happy-path-only spec "
        "shape used here does not occur in any of the four real 2026-09-16 "
        "specs on file -- every one requires `boundary` beyond happy_path. "
        "This test demonstrates a worst case the code path allows, not an "
        "observed production shape; see "
        "test_bad_patch_5_real_spec_a_vacuous_suite_named_with_the_right_words_"
        "is_approved for the same finding measured against a real, multi-"
        "dimension frozen specification. Delete this marker once the gate "
        "requires evidence a test body demonstrates something, not merely "
        "that some test with that name reported PASSED -- a strict xpass "
        "here is that signal."
    ),
)
def test_bad_patch_5_a_vacuous_assert_true_test_is_wrongly_approved() -> None:
    _testing_result, decision = run_testing_then_review(_vacuous_suite_state(business_rules=[]))

    assert decision.status is ReviewerStatus.REJECTED, (
        "the Reviewer approved a test whose entire body is `assert True`: "
        f"score={decision.score}, reason={decision.reason!r}, problems={decision.problems!r}"
    )


def test_bad_patch_5_control_the_same_vacuous_test_is_caught_when_another_dimension_is_required() -> None:
    """Evidence the finding above is precise rather than a broken harness:
    adding one business rule to the same specification makes `business_rule`
    a required dimension too, and the same `assert True` test is correctly
    rejected -- it happens to speak to no dimension's vocabulary. The gap is
    specifically the happy-path-only case, not "every vacuous test passes"."""
    _testing_result, decision = run_testing_then_review(_vacuous_suite_state(
        business_rules=["The endpoint returns 200 when the service is healthy."],
    ))

    assert decision.status is ReviewerStatus.REJECTED
    assert any("business_rule" in problem for problem in decision.problems)


# -----------------------------------------------------------------------------
# Bad patch 5, realistic-spec variant -- the same finding measured against a
# REAL frozen specification rather than the synthetic one above (fix round 1,
# task review Important finding 1). Trace d29547c7b7 is one of the four real
# 2026-09-16 runs frozen by task 7; TestingAgent's own dimension derivation
# requires `boundary`, `business_rule`, `happy_path` and `validation` for its
# specification -- the exact shape none of the four traces lacks, and the
# opposite of the "happy_path-only" spec above.
# -----------------------------------------------------------------------------

_REAL_TRACE = load_trace("d29547c7b7")


def _vacuous_suite_against_real_spec(
    cases: tuple[tuple[str, str], ...],
) -> EngineeringState:
    """Wrap `cases` (identifier, source_excerpt) pairs as one SUCCESS
    `run_tests` result against `_REAL_TRACE`'s own specification."""
    tool = ToolResult(
        tool_name="run_tests", allowed_role=AgentRole.TESTING, status=ToolStatus.SUCCESS,
        input_summary="pytest", output_summary=f"{len(cases)} passed", duration_ms=5,
        evidence_reference="mcp://quality/run_tests",
        test_cases=[
            ExecutedTestCase(identifier=identifier, report="PASSED", source_excerpt=source)
            for identifier, source in cases
        ],
    )
    return EngineeringState(
        run_id="battery-5-real-spec", requirement=_REAL_TRACE.specification.source_requirement,
        specification=_REAL_TRACE.specification, tool_results=[tool],
    )


# Four `assert True` tests, named only to carry the literal words the lexical
# gate (agents/testing.py:_MARKERS, _business_terms) looks for in each of
# d29547c7b7's four required dimensions: boundary ("vacio", a literal boundary
# marker), business_rule ("validar", one of the specification's own >=6-letter
# business-rule words -- computed and confirmed via `_business_terms`),
# validation ("requerido", a literal validation marker), and happy_path
# (automatic from any non-empty, SUCCESS test_cases list). None of the four
# bodies demonstrates anything about the requirement; only the identifiers do
# the lexical work Task 7 showed the gate performs
# (test_lexical_coverage_gate.py).
_NAMED_BUT_VACUOUS_CASES = (
    ("test_happy_path_creates_resource", "assert True"),
    ("test_boundary_nombre_vacio_returns_400", "assert True"),
    ("test_business_rule_validar_nombre_obligatorio", "assert True"),
    ("test_validation_nombre_requerido", "assert True"),
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "task 8 finding (council 2026-09-17), stronger form measured in fix "
        "round 1: the same happy_path mis-attribution (agents/testing.py:"
        "151-158) also APPROVES a fully vacuous suite against a REAL frozen "
        "2026-09-16 specification (trace d29547c7b7, tests/fixtures/replay/"
        "d29547c7b7.json), which requires boundary, business_rule, "
        "validation and happy_path -- not a contrived happy_path-only shape. "
        "Four `assert True` tests, named only to carry the specification's "
        "own lexical markers, satisfy every required dimension and the run "
        "is APPROVED at score 100 with zero problems. This demonstrates the "
        "finding on the same kind of specification ASET's own 2026-09-16 "
        "campaign actually produced, which is what makes it a phase-4 "
        "concern rather than a corner case. Delete this marker once the "
        "gate requires evidence a test body demonstrates something."
    ),
)
def test_bad_patch_5_real_spec_a_vacuous_suite_named_with_the_right_words_is_approved() -> None:
    state = _vacuous_suite_against_real_spec(_NAMED_BUT_VACUOUS_CASES)
    testing_result, decision = run_testing_then_review(state)

    assert testing_result.proposed_tests == [
        "boundary", "business_rule", "happy_path", "validation",
    ], (
        "this test's premise is that the real spec requires more than "
        f"happy_path; got {testing_result.proposed_tests}"
    )
    assert decision.status is ReviewerStatus.REJECTED, (
        "the Reviewer approved a fully vacuous suite against a real, multi-"
        f"dimension specification: score={decision.score}, "
        f"reason={decision.reason!r}, problems={decision.problems!r}"
    )


def test_bad_patch_5_real_spec_control_generic_names_leave_the_same_real_spec_correctly_rejected() -> None:
    """Evidence the finding above turns on the naming trick, not on this real
    spec being uncatchable in general: identical vacuous bodies under generic
    names (no lexical markers) leave `boundary`, `business_rule` and
    `validation` genuinely uncovered, and the same real specification is
    correctly rejected with those three gaps named."""
    generic_cases = (("test_case_one", "assert True"), ("test_case_two", "assert True"))
    state = _vacuous_suite_against_real_spec(generic_cases)
    testing_result, decision = run_testing_then_review(state)

    assert testing_result.coverage_mapping["boundary"] == []
    assert testing_result.coverage_mapping["business_rule"] == []
    assert testing_result.coverage_mapping["validation"] == []
    assert decision.status is ReviewerStatus.REJECTED
    for dimension in ("boundary", "business_rule", "validation"):
        assert any(dimension in problem for problem in decision.problems)
