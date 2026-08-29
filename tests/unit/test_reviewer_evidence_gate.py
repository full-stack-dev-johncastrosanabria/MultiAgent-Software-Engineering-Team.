from engineering_team.agents.reviewer import ReviewerAgent
from engineering_team.contracts.enums import AgentRole, ReviewerStatus, ToolStatus
from engineering_team.contracts.models import TestResult as ContractTestResult
from engineering_team.contracts.models import ToolResult
from engineering_team.contracts.state import EngineeringState
from engineering_team.models.context import build_context

_TEST_REFERENCE = "tests/test_accounts.py::test_lists_accounts"


def _test_result(
    *,
    coverage: dict[str, list[str]],
    executed: list[str] | None = None,
) -> ContractTestResult:
    gaps = [name for name, evidence in coverage.items() if not evidence]
    return ContractTestResult(
        proposed_tests=list(coverage),
        generated_tests=[],
        executed_tests=executed or [_TEST_REFERENCE],
        actual_results=["1 passed"],
        status=ToolStatus.SUCCESS,
        failures=[f"no executed test demonstrates {name}" for name in gaps],
        coverage_mapping=coverage,
        evidence_references=[_TEST_REFERENCE],
    )


def _run_tests_tool(
    *,
    role: AgentRole = AgentRole.TESTING,
    status: ToolStatus = ToolStatus.SUCCESS,
    evidence: str = _TEST_REFERENCE,
) -> ToolResult:
    return ToolResult(
        tool_name="run_tests",
        allowed_role=role,
        input_summary="pytest -q",
        status=status,
        output_summary="1 passed" if status is ToolStatus.SUCCESS else "1 failed",
        duration_ms=10,
        evidence_reference=evidence,
    )


def _review(test_result: ContractTestResult, tools: list[ToolResult]):
    state = EngineeringState(
        run_id="review-evidence-gate",
        requirement="List accounts",
        test_results=[test_result],
        tool_results=tools,
    )
    return ReviewerAgent().execute(build_context(AgentRole.REVIEWER, state, "review"))


def test_reviewer_rejects_success_without_a_real_run_tests_execution() -> None:
    decision = _review(_test_result(coverage={"happy_path": [_TEST_REFERENCE]}), [])

    assert decision.status is ReviewerStatus.REJECTED
    assert decision.subscores["testing"] == 0
    assert any("run_tests" in problem for problem in decision.problems)


def test_reviewer_rejects_green_suite_with_incomplete_required_coverage() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE], "boundary": []}),
        [_run_tests_tool()],
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert decision.subscores["testing"] == 0
    assert any("boundary" in problem for problem in decision.problems)


def test_reviewer_rejects_coverage_that_cites_unexecuted_evidence() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": ["tests/test_fake.py::test_never_executed"]}),
        [_run_tests_tool()],
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any("happy_path" in problem for problem in decision.problems)


def test_reviewer_rejects_run_tests_not_attributed_to_testing_role() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [_run_tests_tool(role=AgentRole.DEVELOPER)],
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any("run_tests" in problem for problem in decision.problems)


def test_reviewer_rejects_coverage_supported_only_by_an_earlier_failed_run() -> None:
    failed_reference = "tests/test_accounts.py::test_boundary_fails"
    decision = _review(
        _test_result(
            coverage={
                "boundary": [failed_reference],
                "happy_path": [_TEST_REFERENCE],
            },
            executed=[failed_reference, _TEST_REFERENCE],
        ),
        [
            _run_tests_tool(status=ToolStatus.FAIL, evidence=failed_reference),
            _run_tests_tool(),
        ],
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any("boundary" in problem for problem in decision.problems)


def test_reviewer_approves_real_green_suite_with_complete_required_coverage() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [_run_tests_tool()],
    )

    assert decision.status is ReviewerStatus.APPROVED
