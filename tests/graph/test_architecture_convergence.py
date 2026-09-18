"""C-02: remediation through Architecture cannot converge, and nothing stops it.

Replays trace a2cb449e2a (flaskapiproduct-dry-20260916j). Five cycles, five
rejections, `return_to=Architecture` every time. Each pass widened the search,
so the ranked denominator grew from 34 to 67 while the visible window stayed
around seven files: coverage *fell* -- 21%, 16%, 10%, 12%, 10% -- and the run
got further from the floor the harder it tried. Nothing in `review_route`
counts unproductive Architecture passes, so the loop only ends when the
iteration budget runs out.

The run's real decisions are replayed rather than invented because the
stagnation detector keys on the text of `problems`: a synthesised rejection
repeated five times would stop on its own repeated failure class and would
prove nothing about what the real run did. The frozen problems differ from
cycle to cycle exactly as they did on 2026-09-16, which is what keeps the
failure-class detector silent and leaves C-02 uncovered.
"""

import re

import pytest
from _replay import load_trace

from engineering_team.contracts.enums import AgentRole
from engineering_team.contracts.state import EngineeringState
from engineering_team.graph.routers import review_route
from engineering_team.graph.stategraph import build_engineering_graph
from engineering_team.repository_evidence import assess_evidence_sufficiency
from tests.integration.test_workflow import ScriptedReviewer

_TRACE = load_trace("a2cb449e2a")

# "27 of 34 ranked files were not read (21% of ...)": the gap sentence carries
# the run's own omitted/ranked counts, so the characterisation below uses the
# integers the run reported instead of back-solving them from the percentage.
_GAP = re.compile(r"(\d+) of (\d+) ranked files were not read")


def _omitted_and_ranked(architecture) -> tuple[int, int]:
    match = _GAP.search(architecture.evidence_gap or "")
    assert match, f"the frozen evidence gap changed shape: {architecture.evidence_gap!r}"
    return int(match.group(1)), int(match.group(2))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "C-02, audit 2026-09-16: nothing routes away from Architecture when its "
        "passes stop being productive. review_route only counts repeated failure "
        "classes, and a real run's problems differ every cycle, so trace "
        "a2cb449e2a went back to Architecture five times out of five. Delete this "
        "marker when fase 2 bounds the architecture loop -- a strict xpass is the "
        "signal that it is bounded."
    ),
)
def test_repeated_architecture_insufficiency_eventually_stops_returning_to_architecture() -> None:
    reviewer = ScriptedReviewer([cycle.reviewer_decision for cycle in _TRACE.cycles])
    graph = build_engineering_graph(
        agent_overrides={AgentRole.REVIEWER: reviewer}, max_remediation_iterations=5
    )

    result = graph.invoke({
        "run_id": "c02-replay",
        "requirement": _TRACE.specification.source_requirement,
    })

    # One design pass, and at most one revisit of it. A second unproductive
    # return means the run is asking a question the evidence budget cannot
    # answer, and asking it again cannot help.
    assert result["route_history"].count("Architecture") <= 2


def test_each_architecture_pass_of_a2cb449e2a_reports_a_new_failure_class() -> None:
    """Why C-03's stagnation detector never fires on this run.

    The two findings are distinct: C-03 stops a run that fails the same way
    twice, and this run never did. Without this, C-02 could be mistaken for a
    C-03 that simply had not tripped yet.
    """
    reviewer = ScriptedReviewer([cycle.reviewer_decision for cycle in _TRACE.cycles])
    graph = build_engineering_graph(
        agent_overrides={AgentRole.REVIEWER: reviewer}, max_remediation_iterations=5
    )

    result = graph.invoke({
        "run_id": "c02-fingerprints",
        "requirement": _TRACE.specification.source_requirement,
    })

    fingerprints = result["failure_fingerprints"]
    assert fingerprints, "the run recorded no rejection at all"
    assert max(fingerprints.count(item) for item in fingerprints) < 3, (
        "a failure class recurred three times, so C-03's detector -- not the "
        "missing architecture bound -- is what ended this run"
    )


def test_a2cb449e2a_coverage_never_reaches_the_floor_across_five_real_cycles() -> None:
    """Characterisation: the loop is unwinnable on the numbers the run recorded.

    Replaying each cycle's own omitted/ranked counts through the live
    sufficiency rule reproduces `evidence_sufficient=False` five times out of
    five, and the coverage it computes falls rather than rises.
    """
    coverages: list[float] = []
    for cycle in _TRACE.cycles:
        assert cycle.architecture is not None
        assert cycle.architecture.evidence_sufficient is False
        omitted, ranked = _omitted_and_ranked(cycle.architecture)

        result = assess_evidence_sufficiency(
            read=ranked - omitted, ranked=ranked, omitted=omitted
        )

        assert result.sufficient is False
        coverages.append(result.coverage)

    assert coverages[-1] < coverages[0], (
        f"coverage did not decay across the run: {coverages}"
    )


def test_an_architecture_rejection_is_routed_back_to_architecture_every_time() -> None:
    """The pure routing rule behind the loop, cycle by cycle, with no counter.

    Each frozen rejection is a fresh failure class, so `repeated_failures`
    stays at one and the route is Architecture again however many passes came
    before it.
    """
    for cycle in _TRACE.cycles:
        route = review_route(
            cycle.reviewer_decision,
            iteration=cycle.cycle - 1,
            max_iterations=5,
            repeated_failures=1,
        )

        assert route == "Architecture"


def test_the_frozen_trace_still_builds_a_valid_engineering_state() -> None:
    """The fixture is only evidence while it still fits the contracts.

    A `StrictModel` refuses unknown fields, so this fails loudly the day fase 2
    changes the shape of a decision or a proposal -- the cue to re-freeze the
    fixture from the export, never to edit it into agreement.
    """
    for cycle in _TRACE.cycles:
        state = EngineeringState(
            run_id=f"c02-state-{cycle.cycle}",
            requirement=_TRACE.specification.source_requirement,
            specification=_TRACE.specification,
            architecture=cycle.architecture,
            review=cycle.reviewer_decision,
        )

        assert state.review is cycle.reviewer_decision
