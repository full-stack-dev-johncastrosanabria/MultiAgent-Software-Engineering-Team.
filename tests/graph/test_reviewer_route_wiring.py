"""C-03's parked debt: `reviewer_next` wired to a real diff, through the graph.

`applied_diff_fingerprint`, `code_unchanged_since_earlier_rejection` and
`rejection_record` are each covered as pure functions in
`tests/graph/test_routers.py`, and `review_route` is covered with
`unchanged_code` passed in by hand. Nothing covered the wiring: that
`stategraph`'s Reviewer node really records what a real `get_diff` returned,
and that `reviewer_next` really reads it back. The task-2 review of `c22b0bf`
parked that gap; these tests close it.

Replays the mechanism of trace f9ca92d099 (spring-demo-dry-20260916e): five
cycles, one unchanging reason, the same code left in the workspace every time.
The frozen decision is that run's own, so the failure class the graph records
is the one it recorded on 2026-09-16.
"""

from pathlib import Path

from _replay import load_trace

from engineering_team.agents.developer import DeveloperAgent
from engineering_team.contracts.enums import ActionMode, AgentRole
from engineering_team.contracts.models import ImplementationResult
from engineering_team.graph.stategraph import build_engineering_graph
from engineering_team.mcp.repository import RepositoryMCP
from tests.integration.test_workflow import PassingQuality, ScriptedReviewer

_TRACE = load_trace("f9ca92d099")
_TARGET = "app/safe.py"


class ScriptedDeveloper(DeveloperAgent):
    """A developer that answers every rejection with the same change.

    That is the real f9ca92d099 behaviour reduced to its mechanism: the
    workspace ends each cycle byte-identical to the last, so `get_diff` returns
    the same cumulative diff and the run cannot learn anything by repeating it.
    """

    def __init__(self, result: ImplementationResult) -> None:
        self.result = result
        self.calls = 0

    def execute(self, envelope):
        self.calls += 1
        return self.result


def _repository(tmp_path: Path) -> RepositoryMCP:
    (tmp_path / "app").mkdir()
    (tmp_path / _TARGET).write_text("value = 1\n", encoding="utf-8")
    return RepositoryMCP(tmp_path)


def _same_change_every_time() -> ImplementationResult:
    return ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=[_TARGET],
        diff="same fix every time",
        evidence=[f"mcp://repository/read_file#{_TARGET}"],
        validation_result="run tests",
        security_surface_changed=False,
        file_contents={_TARGET: "value = 2  # the one fix this developer knows\n"},
    )


def _run(tmp_path: Path, *, with_repository: bool, run_id: str):
    decision = _TRACE.cycles[0].reviewer_decision
    reviewer = ScriptedReviewer([decision] * 5)
    developer = ScriptedDeveloper(_same_change_every_time())
    overrides = {AgentRole.REVIEWER: reviewer, AgentRole.DEVELOPER: developer}
    graph = build_engineering_graph(
        agent_overrides=overrides,
        repository_mcp=_repository(tmp_path) if with_repository else None,
        quality_mcp=PassingQuality(),
        max_remediation_iterations=5,
    )

    result = graph.invoke({
        "run_id": run_id,
        "requirement": "keep the bounded change bounded",
        "repository_context": {"apply_changes": True, "authorized": True},
    })
    return reviewer, developer, result


def test_the_graph_records_the_code_each_rejected_cycle_left_behind(tmp_path: Path) -> None:
    """`rejection_record` reaches state through a real `get_diff`, not by hand."""
    _reviewer, _developer, result = _run(
        tmp_path, with_repository=True, run_id="c03-wiring-record"
    )

    fingerprints = result["applied_diff_fingerprints"]
    assert len(fingerprints) >= 2
    assert all(fingerprints), (
        "the Reviewer node recorded an empty fingerprint, so get_diff never "
        "reached rejection_record and the identity of the rejected code is lost"
    )
    assert fingerprints[0] == fingerprints[1], (
        "the same file contents produced two different fingerprints"
    )


def test_the_graph_stops_when_the_developer_leaves_the_same_code_after_two_rejections(
    tmp_path: Path,
) -> None:
    """`reviewer_next` reads the recorded diff back and stops a cycle early.

    Without the diff evidence this run would take a third cycle before the
    repeated failure class alone stopped it. The control below is the same run
    with no repository, which is exactly the run that does take three.
    """
    reviewer, developer, result = _run(
        tmp_path, with_repository=True, run_id="c03-wiring-stop"
    )

    assert reviewer.calls == 2
    assert developer.calls == 2
    assert result["human_review_required"] is True


def test_without_a_real_diff_the_same_run_needs_a_third_cycle(tmp_path: Path) -> None:
    """The control that makes the stop above attributable to the diff wiring.

    Identical decisions, identical developer, no repository to diff against:
    the fingerprints stay empty, `code_unchanged_since_earlier_rejection`
    refuses to claim anything, and the run falls back to the failure-class
    count. Any change that makes both runs stop at the same cycle has stopped
    reading the diff.
    """
    reviewer, _developer, result = _run(
        tmp_path, with_repository=False, run_id="c03-wiring-control"
    )

    assert reviewer.calls == 3
    assert not any(result["applied_diff_fingerprints"])
    assert result["human_review_required"] is True
