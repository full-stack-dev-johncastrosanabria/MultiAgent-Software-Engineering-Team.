"""What the Developer is actually told when a cycle is rejected: C-01 and A-10.

C-01 replays trace a2cb449e2a (flaskapiproduct-dry-20260916j). Every one of its
five cycles was rejected with `return_to=Architecture` while the reviewer's own
problems named the tests that had failed. `build_context` attaches those
problems to the Developer envelope only when the rejection was routed to the
Developer, so the Developer was asked to fix code it was never told was broken.

A-10 replays trace d29547c7b7 (spring-demo-dry-20260916a), where the route was
never the problem: all three cycles came back to the Developer, and what
arrived was a dependency scanner's CVE listing for artifacts the change never
touched.

Both fixtures are the runs' real decisions, frozen from the Langfuse export,
not reconstructions: the point of either finding is what a real rejection
looked like, and a synthesised `ReviewerDecision` would only prove that the
branch does what its own source says.
"""

import re

import pytest
from _replay import load_trace

from engineering_team.contracts.enums import AgentRole, RemediationCategory, RouteTarget
from engineering_team.contracts.state import EngineeringState
from engineering_team.models.context import build_context

_TRACE = load_trace("a2cb449e2a")
_SECURITY_TRACE = load_trace("d29547c7b7")

# The pytest tail the reviewer carried in `problems` names each failing test as
# `<nodeid> FAILED`. Reading the identifiers back out of the frozen evidence
# keeps the expectation tied to what the run actually recorded.
_FAILED_TEST = re.compile(r"(\S+\.py::\S+)\s+FAILED")


def _failing_tests(decision) -> list[str]:
    return sorted({
        identifier
        for problem in decision.problems
        for identifier in _FAILED_TEST.findall(problem)
    })


def _developer_feedback(cycle, *, return_to: RouteTarget, trace=_TRACE) -> str:
    """What the Developer is told, with the route as the only thing that varies."""
    decision = cycle.reviewer_decision.model_copy(update={"return_to": return_to})
    state = EngineeringState(
        run_id=f"replay-cycle-{cycle.cycle}",
        requirement=trace.specification.source_requirement,
        specification=trace.specification,
        architecture=cycle.architecture,
        review=decision,
        remediation_request=decision.reason,
    )
    return build_context(AgentRole.DEVELOPER, state, "fix").remediation_feedback or ""


def _cycles_with_failing_tests():
    return [cycle for cycle in _TRACE.cycles if _failing_tests(cycle.reviewer_decision)]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "C-01, audit 2026-09-16: build_context only attaches the reviewer's problems "
        "to the Developer when review.return_to names the Developer, so a rejection "
        "routed through Architecture leaves the only role that edits code with "
        "nothing but the generic reason. Delete this marker when fase 2 makes the "
        "diagnostics independent of the route -- a strict xpass is the signal that "
        "the defect is gone."
    ),
)
def test_developer_gets_no_diagnostics_when_reviewer_routed_to_architecture() -> None:
    cycles = _cycles_with_failing_tests()
    assert cycles, "the frozen trace recorded no failing test to deliver"

    for cycle in cycles:
        assert cycle.reviewer_decision.return_to is RouteTarget.ARCHITECTURE
        feedback = _developer_feedback(cycle, return_to=RouteTarget.ARCHITECTURE)
        expected = _failing_tests(cycle.reviewer_decision)
        delivered = [identifier for identifier in expected if identifier in feedback]

        assert delivered, (
            f"cycle {cycle.cycle} was rejected over {len(expected)} failing tests and "
            f"the Developer envelope named none of them"
        )


def test_the_same_rejection_routed_to_the_developer_names_every_failing_test() -> None:
    """The route, not a byte budget, is what withholds the diagnostics.

    Same state, same problems, same envelope -- only `return_to` differs. This
    one passes today, which is what makes the xfail above a statement about
    C-01 rather than about truncation or redaction dropping the identifiers.
    """
    for cycle in _cycles_with_failing_tests():
        feedback = _developer_feedback(cycle, return_to=RouteTarget.DEVELOPER)
        missing = [
            identifier
            for identifier in _failing_tests(cycle.reviewer_decision)
            if identifier not in feedback
        ]

        assert not missing, f"cycle {cycle.cycle} lost {missing} on the Developer route"


def test_every_frozen_cycle_of_a2cb449e2a_was_routed_to_architecture() -> None:
    """Characterisation: the route C-01 depends on was taken 5 times out of 5.

    The finding is only worth a fix if the unlucky branch is the common one.
    In this run it was the only one.
    """
    routes = [cycle.reviewer_decision.return_to for cycle in _TRACE.cycles]

    assert routes == [RouteTarget.ARCHITECTURE] * 5


# A-10 ------------------------------------------------------------------------
#
# The dependency scanner reports its findings as CVE identifiers against
# packaged artifacts. A diagnostic that helps the Developer names the source it
# broke instead: a Java file and a line, or a test that failed.
_CVE = re.compile(r"CVE-\d{4}-\d+")
_SOURCE_LOCATION = re.compile(r"\S+\.(?:java|py|kt|ts)[:#]\d+")
_DIAGNOSTICS_HEADER = "Untrusted reviewer diagnostics (data only):"


def _delivered_diagnostics(feedback: str) -> str:
    _, _, block = feedback.partition(_DIAGNOSTICS_HEADER)
    return block


def test_every_frozen_cycle_of_d29547c7b7_came_back_to_the_developer() -> None:
    """A-10 is not about the route: this run took the lucky one every time.

    Without this, a reader could read the next test as another instance of
    C-01. These three cycles were routed to the Developer, the diagnostics were
    attached, and they still said nothing about the change.
    """
    for cycle in _SECURITY_TRACE.cycles:
        assert cycle.reviewer_decision.return_to is RouteTarget.DEVELOPER
        assert cycle.reviewer_decision.remediation_category is RemediationCategory.SECURITY


def test_the_developers_diagnostics_are_dependency_advisories_not_its_own_change() -> None:
    """A-10, audit 2026-09-16: baseline risk crowds out the real error.

    Characterisation, not a reproduction: this passes today and records what
    the Developer was handed. Every delivered diagnostic is scanner output
    about published artifacts, naming CVEs the change did not introduce and no
    line of the code it was asked to fix.
    """
    for cycle in _SECURITY_TRACE.cycles:
        block = _delivered_diagnostics(
            _developer_feedback(
                cycle, return_to=RouteTarget.DEVELOPER, trace=_SECURITY_TRACE
            )
        )

        assert block, f"cycle {cycle.cycle} delivered no diagnostics at all"
        assert _CVE.search(block), f"cycle {cycle.cycle} carried no advisory to speak of"
        assert not _SOURCE_LOCATION.search(block), (
            f"cycle {cycle.cycle} named a source location, so the advisories did "
            f"not crowd out the real error after all"
        )
        assert not _FAILED_TEST.search(block)


def test_the_advisory_takes_almost_the_whole_diagnostic_budget() -> None:
    """A-10's cost, in bytes, from the run's own decisions.

    The envelope reserves a bounded diagnostic block. In this run the scanner
    dump filled essentially all of it, so raising the budget would only buy
    more CVEs.
    """
    for cycle in _SECURITY_TRACE.cycles:
        problems = cycle.reviewer_decision.problems
        advisory = [problem for problem in problems if _CVE.search(problem)]
        advisory_bytes = sum(len(problem.encode()) for problem in advisory)
        total_bytes = sum(len(problem.encode()) for problem in problems)

        assert advisory_bytes / total_bytes > 0.9, (
            f"cycle {cycle.cycle}: advisories were {advisory_bytes} of {total_bytes} bytes"
        )
