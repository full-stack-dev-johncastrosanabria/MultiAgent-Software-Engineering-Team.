from engineering_team.agents.reviewer import ReviewerAgent
from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecuritySeverity,
    SecurityStatus,
    ToolStatus,
)
from engineering_team.contracts.models import (
    ImplementationResult,
    SecurityReview,
    ToolResult,
)
from engineering_team.contracts.models import TestResult as ContractTestResult
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


_SECURITY_CHECKLIST = {
    "authentication": "PASS",
    "authorization": "PASS",
    "input_validation": "PASS",
    "sensitive_information": "PASS",
    "secrets": "PASS",
    "injection": "PASS",
    "access_control": "PASS",
    "idor": "PASS",
    "logging": "PASS",
    "data_protection": "PASS",
    "api_abuse": "PASS",
    "rate_limiting": "PASS",
    "owasp": "PASS",
}


def _security_review(*, status: SecurityStatus = SecurityStatus.PASS) -> SecurityReview:
    return SecurityReview(
        status=status,
        highest_severity=SecuritySeverity.LOW,
        findings=[],
        recommendations=[],
        sources=[],
        checklist=_SECURITY_CHECKLIST,
        requires_hitl=False,
    )


def _review(
    test_result: ContractTestResult,
    tools: list[ToolResult],
    *,
    implementation: ImplementationResult | None = None,
    apply_changes: bool = False,
    security_review: SecurityReview | None = None,
):
    state = EngineeringState(
        run_id="review-evidence-gate",
        requirement="List accounts",
        repository_context={"apply_changes": apply_changes, "authorized": apply_changes},
        implementation=implementation,
        security_review=security_review,
        test_results=[test_result],
        tool_results=tools,
    )
    return ReviewerAgent().execute(build_context(AgentRole.REVIEWER, state, "review"))


def _implementation(
    *,
    mode: ActionMode = ActionMode.APPLIED,
    contents: dict[str, str] | None = None,
) -> ImplementationResult:
    return ImplementationResult(
        action_mode=mode,
        changed_files=["app/accounts.py"],
        diff="implement account listing",
        evidence=["mcp://repository/read_file#app/accounts.py"],
        validation_result="run tests",
        security_surface_changed=False,
        file_contents=contents or {},
    )


def _repository_tool(name: str, output: str) -> ToolResult:
    return ToolResult(
        tool_name=name,
        allowed_role=AgentRole.DEVELOPER,
        input_summary="path=app/accounts.py" if name == "update_file" else "git diff",
        status=ToolStatus.SUCCESS,
        output_summary=output,
        duration_ms=10,
        evidence_reference=f"mcp://repository/{name}",
    )


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


def test_reviewer_rejects_proposal_only_apply_with_green_baseline() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [_run_tests_tool()],
        implementation=_implementation(mode=ActionMode.PROPOSED),
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert decision.remediation_category is RemediationCategory.IMPLEMENTATION
    assert decision.return_to is RouteTarget.DEVELOPER
    assert any("APPLIED" in problem for problem in decision.problems)


def test_reviewer_rejects_applied_content_without_write_evidence() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [_run_tests_tool()],
        implementation=_implementation(contents={"app/accounts.py": "value = 2\n"}),
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any("write" in problem for problem in decision.problems)
    assert any("diff" in problem for problem in decision.problems)


def test_reviewer_rejects_successful_write_with_empty_resulting_diff() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [
            _repository_tool("update_file", "app/accounts.py"),
            _repository_tool("get_diff", ""),
            _run_tests_tool(),
        ],
        implementation=_implementation(contents={"app/accounts.py": "value = 2\n"}),
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any("non-empty" in problem for problem in decision.problems)


def test_reviewer_rejects_authored_text_without_final_newline() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [
            _repository_tool("update_file", "app/accounts.py"),
            _repository_tool(
                "get_diff",
                "--- a/app/accounts.py\n+++ b/app/accounts.py\n@@ -1 +1 @@\n-old\n+new",
            ),
            _run_tests_tool(),
        ],
        implementation=_implementation(contents={"app/accounts.py": "value = 2"}),
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any("newline" in problem for problem in decision.problems)


def test_reviewer_approves_green_tests_despite_trailing_whitespace_only() -> None:
    # Style nit alone must not HITL when tests already proved the change.
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [
            _repository_tool("update_file", "app/accounts.py"),
            _repository_tool(
                "get_diff",
                "--- a/app/accounts.py\n+++ b/app/accounts.py\n@@ -1 +1 @@\n-old\n+new   ",
            ),
            _run_tests_tool(),
        ],
        implementation=_implementation(contents={"app/accounts.py": "value = 2\n"}),
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.APPROVED


def test_reviewer_reports_test_and_diff_failures_in_the_same_cycle() -> None:
    test_result = ContractTestResult(
        proposed_tests=["happy_path"],
        generated_tests=[],
        executed_tests=[_TEST_REFERENCE],
        actual_results=["1 failed"],
        status=ToolStatus.FAIL,
        failures=[f"FAILED {_TEST_REFERENCE} - assert '2.00' == 2.0"],
        coverage_mapping={"happy_path": []},
        evidence_references=[_TEST_REFERENCE],
    )
    decision = _review(
        test_result,
        [
            _repository_tool("update_file", "app/accounts.py"),
            _repository_tool(
                "get_diff",
                "--- a/app/accounts.py\n+++ b/app/accounts.py\n@@ -1 +1 @@\n-old\n+new   ",
            ),
            _run_tests_tool(status=ToolStatus.FAIL),
        ],
        implementation=_implementation(contents={"app/accounts.py": "value = 2"}),
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any("not demonstrated" in problem for problem in decision.problems)
    assert any("newline" in problem for problem in decision.problems)
    assert any("trailing whitespace" in problem for problem in decision.problems)


def test_reviewer_approves_fully_applied_change_with_green_tests() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [
            _repository_tool("update_file", "app/accounts.py"),
            _repository_tool(
                "get_diff",
                "--- a/app/accounts.py\n+++ b/app/accounts.py\n"
                "@@ -1,2 +1,2 @@\n existing debt   \n-old\n+new",
            ),
            _run_tests_tool(),
        ],
        implementation=_implementation(contents={"app/accounts.py": "value = 2\n"}),
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.APPROVED

def test_reviewer_approves_empty_security_coverage_when_security_pass() -> None:
    """apply-399a301c: Security PASS covers the security dimension; do not HITL."""
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE], "security": []}),
        [_run_tests_tool()],
        security_review=_security_review(status=SecurityStatus.PASS),
    )

    assert decision.status is ReviewerStatus.APPROVED
    assert not any("security" in problem for problem in decision.problems)


def test_reviewer_rejects_empty_security_coverage_without_security_pass() -> None:
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE], "security": []}),
        [_run_tests_tool()],
    )

    assert decision.status is ReviewerStatus.REJECTED
    assert any(
        "required coverage dimension has no evidence: security" in problem
        for problem in decision.problems
    )

def test_reviewer_ignores_whitespace_noop_writes_outside_diff() -> None:
    """SUCCESS update_file with no get_diff footprint is WS noop (product.py)."""
    implementation = ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=["app/routes/accounts.py", "app/models/product.py"],
        diff="implement account listing",
        evidence=["mcp://repository/read_file#app/routes/accounts.py"],
        validation_result="run tests",
        security_surface_changed=False,
        file_contents={
            "app/routes/accounts.py": "value = 2\n",
            "app/models/product.py": "class Product:\n    pass\n",
        },
    )
    decision = _review(
        _test_result(coverage={"happy_path": [_TEST_REFERENCE]}),
        [
            _repository_tool("update_file", "app/routes/accounts.py"),
            _repository_tool("update_file", "app/models/product.py"),
            _repository_tool(
                "get_diff",
                "--- a/app/routes/accounts.py\n+++ b/app/routes/accounts.py\n"
                "@@ -1 +1 @@\n-old\n+new",
            ),
            _run_tests_tool(),
        ],
        implementation=implementation,
        apply_changes=True,
    )

    assert decision.status is ReviewerStatus.APPROVED
    assert not any("product.py" in problem for problem in decision.problems)

