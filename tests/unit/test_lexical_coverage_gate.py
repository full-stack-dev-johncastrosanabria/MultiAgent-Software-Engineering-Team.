"""C-04: the coverage gate reads words, so a green suite fails for its language.

Replays trace 38863321ef (spring-demo-dry-20260916d). Product wrote the
specification in Spanish; the Java suite was written, and passed, in English.
`run_tests` was SUCCESS in every cycle and the run was rejected anyway, four
times out of five, because no required coverage dimension could find one of the
specification's own words inside an English test name.

The specification is the frozen one that run worked from, not a paraphrase:
which words the gate demands is derived from that exact text, so a rewritten
specification would be testing a different gate.

Nothing here asserts the wording of a problem. The gate's message has already
grown since the campaign -- it now also names `@DisplayName` and
`[Fact(DisplayName=...)]` -- while the rule behind it did not change. What these
tests pin is the verdict and which dimensions found evidence.
"""

import pytest
from _replay import load_trace, run_testing_then_review

from engineering_team.contracts.enums import AgentRole, ReviewerStatus, ToolStatus
from engineering_team.contracts.models import ExecutedTestCase, ToolResult
from engineering_team.contracts.models import TestResult as ContractTestResult
from engineering_team.contracts.state import EngineeringState

_TRACE = load_trace("38863321ef")

# The three behaviours the specification asks for, as the real run's Java suite
# named them: empty name rejected, blank name rejected, valid name accepted.
_ENGLISH_SUITE = (
    (
        "ProductControllerTest::createProductWithEmptyNameShouldReturn400",
        (
            'mockMvc.perform(post("/products").content("{\\"name\\":\\"\\"}"))'
            ".andExpect(status().isBadRequest());"
        ),
    ),
    (
        "ProductControllerTest::createProductWithBlankNameShouldReturn400",
        (
            'mockMvc.perform(post("/products").content("{\\"name\\":\\"   \\"}"))'
            ".andExpect(status().isBadRequest());"
        ),
    ),
    (
        "ProductControllerTest::createProductWithValidNameShouldReturn201",
        (
            'mockMvc.perform(post("/products").content("{\\"name\\":\\"Widget\\"}"))'
            ".andExpect(status().isCreated());"
        ),
    ),
)

# The same three behaviours, named and described in the specification's own
# language. Identical evidence, identical green run: only the words differ.
_REJECTION_IN_SPANISH = (
    "El campo nombre es obligatorio: si está vacío o solo contiene espacios la API "
    "rechaza la solicitud con un error 400 indicando el campo requerido, en vez de "
    "fallar contra la base de datos."
)

_SPANISH_SUITE = (
    ("ProductControllerTest::crearRecursoConNombreVacioRechazaConError400",
     _REJECTION_IN_SPANISH),
    ("ProductControllerTest::crearRecursoConNombreEnEspaciosRechazaConError400",
     _REJECTION_IN_SPANISH),
    (
        "ProductControllerTest::crearRecursoConNombreValidoDevuelve201",
        (
            "Crear un recurso con un nombre válido devuelve 201 y el recurso queda "
            "persistido correctamente."
        ),
    ),
)


def _green_suite(cases: tuple[tuple[str, str], ...]) -> ToolResult:
    """A real passing run, reported per test case the way the Java runner does."""
    return ToolResult(
        tool_name="run_tests",
        allowed_role=AgentRole.TESTING,
        status=ToolStatus.SUCCESS,
        input_summary="mvn test",
        output_summary=f"Tests run: {len(cases)}, Failures: 0, Errors: 0, Skipped: 0",
        duration_ms=10,
        evidence_reference="mcp://quality/run_tests",
        test_cases=[
            ExecutedTestCase(identifier=identifier, report="PASSED", source_excerpt=source)
            for identifier, source in cases
        ],
    )


def _run_testing_then_review(cases) -> tuple[ContractTestResult, object]:
    """What Testing claims the suite covers, and what Reviewer does about it.

    Delegates to `_replay.run_testing_then_review`, Task 7's shared Testing-then-
    Reviewer chain (moved there in task 8's fix round 1 so
    `test_known_bad_patches.py` could reuse it instead of keeping a second
    copy). Only the state-building is specific to this file's replayed trace.
    """
    state = EngineeringState(
        run_id="c04-replay",
        requirement=_TRACE.specification.source_requirement,
        specification=_TRACE.specification,
        tool_results=[_green_suite(cases)],
    )
    return run_testing_then_review(state)


def _dimensions_without_evidence(testing: ContractTestResult) -> list[str]:
    return sorted(name for name, evidence in testing.coverage_mapping.items() if not evidence)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "C-04, audit 2026-09-16: the coverage gate requires a literal word from the "
        "specification inside a test's name or body, so a green English suite that "
        "demonstrates a Spanish-worded rule is rejected for dimensions it does "
        "cover. Trace 38863321ef was rejected this way in four of its five cycles. "
        "Delete this marker when fase 2 makes lexical coverage advisory -- a strict "
        "xpass is the signal that the gate stopped judging vocabulary."
    ),
)
def test_a_green_suite_satisfying_the_rule_in_english_is_not_rejected_for_spanish_wording() -> None:
    _testing, decision = _run_testing_then_review(_ENGLISH_SUITE)

    assert decision.status is ReviewerStatus.APPROVED


def test_the_same_green_suite_is_approved_once_its_names_use_the_specifications_words() -> None:
    """The verdict turns on vocabulary, not on what the suite proved.

    Same three behaviours, same passing run, same specification. Renaming the
    cases into the specification's own language closes every gap and the run is
    approved, which is what makes the xfail above a statement about the gate
    rather than about a suite that really was thin.
    """
    english, english_decision = _run_testing_then_review(_ENGLISH_SUITE)
    spanish, spanish_decision = _run_testing_then_review(_SPANISH_SUITE)

    assert english.status is ToolStatus.SUCCESS
    assert spanish.status is ToolStatus.SUCCESS
    assert english.coverage_mapping.keys() == spanish.coverage_mapping.keys()
    assert _dimensions_without_evidence(spanish) == []
    assert _dimensions_without_evidence(english)
    assert spanish_decision.status is ReviewerStatus.APPROVED
    assert english_decision.status is ReviewerStatus.REJECTED


def test_the_rejected_english_suite_really_did_run_and_really_did_pass() -> None:
    """Characterisation: nothing failed. The run was rejected on evidence it had.

    `run_tests` was SUCCESS in all five real cycles of 38863321ef; the gate's
    objection was never that a test broke.
    """
    testing, decision = _run_testing_then_review(_ENGLISH_SUITE)

    assert testing.status is ToolStatus.SUCCESS
    assert len(testing.executed_tests) == 1
    assert decision.status is ReviewerStatus.REJECTED


def test_four_of_the_five_frozen_cycles_were_rejected_by_the_coverage_gate() -> None:
    """Characterisation: the gate, not the code, decided most of this run.

    Cycles 1, 2, 4 and 5 were TESTING remediations; cycle 3 was an
    IMPLEMENTATION rejection about a missing trailing newline, which is a
    different objection and is counted separately here so the C-04 total is
    not inflated.
    """
    categories = [cycle.reviewer_decision.remediation_category for cycle in _TRACE.cycles]

    assert [item.value for item in categories] == [
        "TESTING", "TESTING", "IMPLEMENTATION", "TESTING", "TESTING"
    ]
    assert all(
        cycle.reviewer_decision.status is ReviewerStatus.REJECTED for cycle in _TRACE.cycles
    )
