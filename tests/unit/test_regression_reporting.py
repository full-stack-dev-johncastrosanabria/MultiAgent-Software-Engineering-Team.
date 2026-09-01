"""A broken test and a failing new test are different news.

Measured on a real run: the Developer was told "failed tests require
implementation remediation" with raw pytest output, three cycles in a row. Two of
the four failures were tests that had passed before its change —
`test_get_products_empty` and `test_filter_products_by_price`, both broken by
fixtures that leaked products into shared state. Nothing in the message said the
word "regression", so it kept working on the wrong thing.
"""

from __future__ import annotations

from engineering_team.testing_evidence import (
    classify_failures,
    failing_tests,
    failure_diagnostics,
    passing_tests,
)

PYTEST_OUTPUT = """
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-8.4.2
collected 15 items

tests/test_products.py ....F..F...F.F.                                   [100%]

=================================== FAILURES ===================================
FAILED tests/test_products.py::TestProducts::test_get_products_empty - assert 3 == 0
FAILED tests/test_products.py::TestProducts::test_filter_products_by_price - assert 4 == 2
FAILED tests/test_products.py::TestProducts::test_get_low_stock_products_default_threshold
FAILED tests/test_products.py::TestProducts::test_get_low_stock_products_custom_threshold
================== 4 failed, 11 passed, 49 warnings in 0.76s ===================
"""

CLEAN_OUTPUT = """
tests/test_products.py::TestProducts::test_get_products_empty PASSED
tests/test_products.py::TestProducts::test_filter_products_by_price PASSED
tests/test_products.py::TestProducts::test_create_product PASSED
======================== 3 passed, 12 warnings in 0.42s ========================
"""

DETAILED_PYTEST_OUTPUT = """
=================================== FAILURES ===================================
_____________ TestLowStockEndpoint.test_low_stock_custom_threshold _____________
tests/test_products.py:283: in test_low_stock_custom_threshold
    assert data['count'] == 2  # A (3), B (8)
    ^^^^^^^^^^^^^^^^^^^^^^^^^
E   assert 1 == 2
__________ TestLowStockEndpoint.test_low_stock_non_integer_threshold ___________
tests/test_products.py:303: in test_low_stock_non_integer_threshold
    assert response.status_code == 400
E   assert 200 == 400
E    +  where 200 = <WrapperTestResponse streamed [200 OK]>.status_code
=========================== short test summary info ============================
FAILED tests/test_products.py::TestLowStockEndpoint::test_low_stock_custom_threshold
FAILED tests/test_products.py::TestLowStockEndpoint::test_low_stock_non_integer_threshold
========================= 2 failed, 13 passed in 0.51s =========================
"""


def test_failing_identifiers_are_read_from_the_output() -> None:
    failures = failing_tests(PYTEST_OUTPUT)
    assert "tests/test_products.py::TestProducts::test_get_products_empty" in failures
    assert len(failures) == 4


def test_a_clean_run_reports_no_failures() -> None:
    assert failing_tests(CLEAN_OUTPUT) == ()


def test_parametrized_identifier_with_spaces_keeps_its_full_node_id() -> None:
    identifier = "tests/test_lookup.py::test_lookup[value with space]"
    output = "\n".join([
        "=================================== FAILURES ===================================",
        "________________ test_lookup[value with space] _________________",
        "tests/test_lookup.py:12: in test_lookup[value with space]",
        "E   assert 'actual' == 'expected'",
        "=========================== short test summary info ============================",
        f"FAILED {identifier}",
    ])

    failures = failing_tests(output)
    diagnostics = failure_diagnostics(output, failures)

    assert failures == (identifier,)
    assert diagnostics[identifier].endswith("assert 'actual' == 'expected'")
    assert passing_tests(f"{identifier} PASSED") == (identifier,)


def test_repeated_test_names_keep_their_own_failure_blocks() -> None:
    first = "tests/a/test_lookup.py::test_duplicate"
    second = "tests/b/test_lookup.py::test_duplicate"
    output = "\n".join([
        "=================================== FAILURES ===================================",
        "________________________ test_duplicate _________________________",
        "tests/a/test_lookup.py:10: in test_duplicate",
        "E   assert 'first-actual' == 'first-expected'",
        "________________________ test_duplicate _________________________",
        "tests/b/test_lookup.py:20: in test_duplicate",
        "E   assert 'second-actual' == 'second-expected'",
        "=========================== short test summary info ============================",
        f"FAILED {first}",
        f"FAILED {second}",
    ])

    diagnostics = failure_diagnostics(output, failing_tests(output))

    assert "first-actual" in diagnostics[first]
    assert "second-actual" in diagnostics[second]


def test_failure_diagnostics_are_bounded_and_redacted() -> None:
    sections = []
    summary = []
    for index in range(7):
        sections.append(
            f"________ TestBatch.test_case_{index} ________\n"
            f"tests/test_batch.py:{index + 1}: in test_case_{index}\n"
            f"E   AssertionError: password=topsecret-{index} {'x' * 1200}"
        )
        summary.append(
            f"FAILED tests/test_batch.py::TestBatch::test_case_{index}"
        )
    output = "\n".join([
        "=================================== FAILURES ===================================",
        *sections,
        "=========================== short test summary info ============================",
        *summary,
    ])

    diagnostics = failure_diagnostics(output, failing_tests(output))

    assert len(diagnostics) == 6
    assert sum(len(item.encode()) for item in diagnostics.values()) <= 4096
    assert all(len(item.encode()) <= 768 for item in diagnostics.values())
    assert "topsecret" not in " ".join(diagnostics.values())
    assert "[REDACTED]" in " ".join(diagnostics.values())


def test_passing_identifiers_are_read_for_the_baseline() -> None:
    passing = passing_tests(CLEAN_OUTPUT)
    assert "tests/test_products.py::TestProducts::test_get_products_empty" in passing
    assert len(passing) == 3


# -- the distinction that matters --------------------------------------------


def test_a_test_that_passed_before_is_a_regression() -> None:
    baseline = passing_tests(CLEAN_OUTPUT)
    broken, _ = classify_failures(failing_tests(PYTEST_OUTPUT), baseline)

    assert "tests/test_products.py::TestProducts::test_get_products_empty" in broken
    assert "tests/test_products.py::TestProducts::test_filter_products_by_price" in broken
    assert len(broken) == 2


def test_a_test_that_never_passed_is_not_a_regression() -> None:
    """The new low-stock tests failing is expected news, not a break."""
    baseline = passing_tests(CLEAN_OUTPUT)
    _, fresh = classify_failures(failing_tests(PYTEST_OUTPUT), baseline)

    assert all("low_stock" in name for name in fresh)
    assert len(fresh) == 2


def test_without_a_baseline_nothing_is_called_a_regression() -> None:
    """Silence about the past is not evidence that nothing broke."""
    broken, fresh = classify_failures(failing_tests(PYTEST_OUTPUT), ())
    assert broken == ()
    assert len(fresh) == 4


# -- what the Developer is actually told -------------------------------------


def _state(baseline: tuple[str, ...], output: str = PYTEST_OUTPUT):
    from engineering_team.contracts.enums import AgentRole, ToolStatus
    from engineering_team.contracts.models import TestResult, ToolResult
    from engineering_team.contracts.state import EngineeringState

    return EngineeringState(
        run_id="r1", requirement="add low stock endpoint",
        baseline_tests=list(baseline),
        test_results=[TestResult(
            proposed_tests=["happy_path"], generated_tests=[],
            executed_tests=["run_tests"], actual_results=[output],
            status=ToolStatus.FAIL, failures=[output],
            coverage_mapping={"happy_path": ["run_tests"]},
            evidence_references=["run_tests"],
        )],
        tool_results=[ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING,
            status=ToolStatus.FAIL, input_summary="pytest",
            output_summary=output, duration_ms=1,
        )],
    )


def _decide(state):
    from engineering_team.agents.reviewer import ReviewerAgent
    from engineering_team.contracts.enums import AgentRole
    from engineering_team.models.context import build_context

    return ReviewerAgent().execute(build_context(AgentRole.REVIEWER, state, "review"))


def test_the_developer_is_told_which_tests_it_broke() -> None:
    """Three cycles were spent because this sentence did not exist."""
    decision = _decide(_state(passing_tests(CLEAN_OUTPUT)))
    joined = " ".join(decision.problems)

    assert "REGRESSION" in joined
    assert "test_get_products_empty" in joined
    assert "test_filter_products_by_price" in joined


def test_the_new_failures_are_reported_separately() -> None:
    decision = _decide(_state(passing_tests(CLEAN_OUTPUT)))
    regression_line = next(p for p in decision.problems if "REGRESSION" in p)

    assert "low_stock" not in regression_line, "a new test is not a regression"


def test_without_a_baseline_nothing_is_claimed_about_the_past() -> None:
    decision = _decide(_state(()))
    assert not any("REGRESSION" in p for p in decision.problems)


def test_developer_receives_the_failed_assertions_without_testing_access() -> None:
    from engineering_team.contracts.enums import AgentRole
    from engineering_team.models.context import build_context

    state = _state((), DETAILED_PYTEST_OUTPUT)
    decision = _decide(state)
    remediation = state.model_copy(update={
        "review": decision,
        "remediation_request": decision.reason,
    })
    envelope = build_context(AgentRole.DEVELOPER, remediation, "fix")

    assert "test_low_stock_custom_threshold" in envelope.remediation_feedback
    assert "assert 1 == 2" in envelope.remediation_feedback
    assert "test_low_stock_non_integer_threshold" in envelope.remediation_feedback
    assert "assert 200 == 400" in envelope.remediation_feedback
    assert "test_results" not in envelope.state_projection
    assert "run_tests" not in envelope.allowed_tools


def test_regression_diagnostic_has_priority_when_the_budget_is_full() -> None:
    from engineering_team.contracts.enums import AgentRole
    from engineering_team.models.context import build_context

    sections = []
    summary = []
    identifiers = []
    module = "tests/" + "nested_component/" * 10 + "test_batch.py"
    for index in range(7):
        identifier = f"{module}::TestBatch::test_case_{index}"
        identifiers.append(identifier)
        sections.append(
            f"________ TestBatch.test_case_{index} ________\n"
            f"{module}:{index + 1}: in test_case_{index}\n"
            f"E   assert {index} == 99 {'x' * 1000}"
        )
        summary.append(f"FAILED {identifier}")
    output = "\n".join([
        "=================================== FAILURES ===================================",
        *sections,
        "=========================== short test summary info ============================",
        *summary,
    ])

    state = _state((identifiers[-1],), output)
    decision = _decide(state)
    remediation = state.model_copy(update={
        "review": decision,
        "remediation_request": decision.reason,
    })
    feedback = build_context(AgentRole.DEVELOPER, remediation, "fix").remediation_feedback

    assert "REGRESSION" in feedback
    assert "assert 6 == 99" in feedback


def test_langgraph_schema_keeps_the_test_baseline() -> None:
    """A field missing from WorkflowState is silently dropped at graph entry."""
    from engineering_team.graph.stategraph import WorkflowState

    assert "baseline_tests" in WorkflowState.__annotations__
