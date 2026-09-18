"""What the change receipt states, and what it must not leave out (A-05).

`run_on_project`'s evidence dict is the only artefact a reader gets once the
run is over and its checkout is gone, so every claim in it has to be one the
run can support. Three claims were not:

- `applied_diff` took the *first* `get_diff` and never looked at its status, so
  a superseded diff -- or a refused one -- could be presented as the change.
- Nothing said what the run left open, so residual risk the system decided not
  to fix, objections nobody closed, and verification that never ran all
  disappeared by omission behind a receipt that read as complete.
- Nothing said which commit the run worked on, and by the time anyone reads the
  report the ephemeral clone that could answer has been deleted.

Nothing in the suite pinned any of this before these tests existed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from engineering_team.apply_run import run_on_project
from engineering_team.config import Settings
from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    ReviewerStatus,
    ToolStatus,
)
from engineering_team.contracts.models import (
    BASELINE_RISK_PREFIX,
    ImplementationResult,
    ReviewerDecision,
    ToolResult,
)


def _diff(summary: str, *, status: ToolStatus = ToolStatus.SUCCESS) -> ToolResult:
    return ToolResult(
        tool_name="get_diff",
        allowed_role=AgentRole.DEVELOPER,
        status=status,
        input_summary="",
        output_summary=summary,
        duration_ms=1,
    )


def _review(
    *, status: ReviewerStatus = ReviewerStatus.APPROVED, problems: list[str] | None = None
) -> ReviewerDecision:
    return ReviewerDecision(
        status=status,
        score=100 if status is ReviewerStatus.APPROVED else 20,
        subscores={
            "requirements": 100,
            "architecture": 100,
            "security": 100,
            "testing": 100,
            "implementation": 100,
            "rag_grounding": 100,
        },
        problems=problems or [],
        reason="validated evidence satisfies acceptance checks",
        confidence=1,
    )


def _state(
    *,
    tool_results: list[ToolResult] | None = None,
    review: ReviewerDecision | None = None,
    final_status: str | None = "APPROVED",
) -> dict:
    return {
        "run_id": "apply-receipt-1",
        "implementation": ImplementationResult(
            action_mode=ActionMode.APPLIED,
            changed_files=["app.py"],
            diff="x = 2",
            evidence=["mcp://repository/update_file"],
            validation_result="ok",
            security_surface_changed=False,
            file_contents={"app.py": "x = 2\n"},
        ),
        "review": _review() if review is None else review,
        "tool_results": tool_results or [],
        "errors": [],
        "final_status": final_status,
        "route_history": [],
        "iteration": 1,
        "model_usage": [],
        "human_review_required": False,
    }


def _receipt(project: Path, state: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    trace = SimpleNamespace(trace_id="trace-receipt", live=False)
    monkeypatch.setattr(
        "engineering_team.apply_run.execute_on_project",
        lambda *a, **k: (state, trace, 0.01, False),
    )
    return run_on_project(Settings(), project_path=project, specification="change")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    return root


# -- applied_diff: the last one, and only if it succeeded ---------------------


def test_applied_diff_is_the_last_get_diff_and_not_the_first(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_diff is cumulative, so only its latest result describes the change.

    A run that remediates calls get_diff once per cycle. Reporting the first
    one hands the reader the change as it stood before the fix.
    """
    state = _state(tool_results=[_diff("diff-1"), _diff("diff-2")])

    evidence = _receipt(project, state, monkeypatch)

    assert evidence["applied_diff"] == "diff-2"


def test_applied_diff_ignores_a_get_diff_that_did_not_succeed(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DENIED or UNAVAILABLE get_diff carries no diff, only a reason.

    Unsuccessful results bracket the real ones here on purpose, so neither half
    of the fix can pass on its own: taking the first presents a refusal as the
    change, and taking the last without reading the status replaces a real diff
    with an empty string and still calls it the change that was applied.
    """
    state = _state(
        tool_results=[
            _diff("", status=ToolStatus.DENIED),
            _diff("diff-1"),
            _diff("diff-2"),
            _diff("", status=ToolStatus.UNAVAILABLE),
        ]
    )

    evidence = _receipt(project, state, monkeypatch)

    assert evidence["applied_diff"] == "diff-2"


def test_applied_diff_is_empty_when_no_get_diff_ever_succeeded(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(tool_results=[_diff("ignored", status=ToolStatus.FAIL)])

    evidence = _receipt(project, state, monkeypatch)

    assert evidence["applied_diff"] == ""


# -- target_repo_sha: which commit the run actually worked on ----------------


def test_target_repo_sha_is_the_commit_the_checkout_was_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    git = ["git", "-C", str(root)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True, capture_output=True)
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [*git, "-c", "user.email=aset@example.invalid", "-c", "user.name=ASET",
         "commit", "-qm", "seed"],
        check=True, capture_output=True,
    )
    expected = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    evidence = _receipt(root, _state(), monkeypatch)

    assert evidence["target_repo_sha"] == expected


def test_target_repo_sha_is_none_and_does_not_raise_outside_a_git_repository(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """None means "no SHA", and the key is always there so its absence cannot
    be read as "not computed yet"."""
    evidence = _receipt(project, _state(), monkeypatch)

    assert "target_repo_sha" in evidence
    assert evidence["target_repo_sha"] is None


# -- unresolved_risks: what the run left open --------------------------------


def test_unresolved_risks_is_empty_when_an_approved_run_left_nothing_open(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(tool_results=[_diff("diff-1")])

    evidence = _receipt(project, state, monkeypatch)

    assert evidence["unresolved_risks"] == []


def test_unresolved_risks_names_baseline_risk_an_approved_run_did_not_fix(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Baseline dependency risk is deliberately kept out of remediation.

    `graph.routers.remediation_fingerprint` drops it so a repeat is not read as
    progress, which means nothing ever closes it. A receipt that does not say
    so reports an approval with unstated risk behind it.
    """
    problem = f"{BASELINE_RISK_PREFIX} reported by scanners; CVE-2026-0001 in urllib3"
    state = _state(review=_review(problems=[problem]))

    evidence = _receipt(project, state, monkeypatch)

    assert {"kind": "baseline_risk", "source": "reviewer", "detail": problem} in evidence[
        "unresolved_risks"
    ]


def test_unresolved_risks_names_the_objections_a_rejected_run_left_open(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(
        review=_review(
            status=ReviewerStatus.REJECTED,
            problems=["no test covers the new branch", "the endpoint is unauthenticated"],
        ),
        final_status="HUMAN_REVIEW_REQUIRED",
    )

    evidence = _receipt(project, state, monkeypatch)

    assert [
        item["detail"] for item in evidence["unresolved_risks"]
        if item["kind"] == "open_objection"
    ] == ["no test covers the new branch", "the endpoint is unauthenticated"]


def test_unresolved_risks_does_not_call_an_approved_runs_problems_open(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An approved run's non-baseline notes were answered, not left open."""
    state = _state(review=_review(problems=["style nit the Reviewer accepted anyway"]))

    evidence = _receipt(project, state, monkeypatch)

    assert [item["kind"] for item in evidence["unresolved_risks"]] == []


def test_unresolved_risks_names_a_run_that_never_reached_a_reviewer(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`review: null` next to no error reads as nothing to report.

    A run whose chain died before the Reviewer left everything open, and that is
    a different outcome from a run that was looked at and approved.
    """
    state = _state(final_status=None)
    state["review"] = None

    evidence = _receipt(project, state, monkeypatch)

    assert [item["kind"] for item in evidence["unresolved_risks"]] == ["unreviewed"]


def test_unresolved_risks_names_a_tool_whose_last_word_was_not_success(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests that never ran are not tests that passed."""
    state = _state(
        tool_results=[
            ToolResult(
                tool_name="run_tests",
                allowed_role=AgentRole.TESTING,
                status=ToolStatus.UNAVAILABLE,
                input_summary="",
                output_summary="",
                duration_ms=0,
                error="venv creation failed in container",
            ),
            _diff("diff-1"),
        ]
    )

    evidence = _receipt(project, state, monkeypatch)

    assert {
        "kind": "unverified",
        "source": "run_tests",
        "detail": "UNAVAILABLE: venv creation failed in container",
    } in evidence["unresolved_risks"]


def test_unresolved_risks_keeps_only_a_tools_last_outcome(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool that failed and then passed closed its own risk.

    Listing every failed attempt would report a fixed problem as an open one,
    which is the same dishonesty as the first-diff receipt in the other
    direction.
    """
    def attempt(status: ToolStatus, reason: str = "") -> ToolResult:
        return ToolResult(
            tool_name="run_tests",
            allowed_role=AgentRole.TESTING,
            status=status,
            input_summary="",
            output_summary="",
            duration_ms=1,
            error=reason or None,
        )

    state = _state(tool_results=[attempt(ToolStatus.FAIL, "2 failed"), attempt(ToolStatus.SUCCESS)])

    evidence = _receipt(project, state, monkeypatch)

    assert [item for item in evidence["unresolved_risks"] if item["kind"] == "unverified"] == []
