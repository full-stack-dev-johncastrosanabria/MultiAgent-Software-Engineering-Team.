"""Post-APPROVED delivery wiring in apply_run (ADR 6)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from engineering_team.apply_run import run_on_project
from engineering_team.config import Settings
from engineering_team.contracts.enums import ActionMode, ReviewerStatus
from engineering_team.contracts.models import ImplementationResult, ReviewerDecision
from engineering_team.delivery import Proposal, build_delivery


def test_build_delivery_still_none_by_default() -> None:
    assert Settings().delivery_backend == "none"
    assert build_delivery(Settings()) is None


def _approved_state(*, run_id: str = "apply-delivery-1") -> dict:
    implementation = ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=["app/models/product.py"],
        diff="add sku",
        evidence=["mcp://repository/update_file"],
        validation_result="ok",
        security_surface_changed=False,
        file_contents={"app/models/product.py": "class Product:\n    sku: str\n"},
    )
    review = ReviewerDecision(
        status=ReviewerStatus.APPROVED,
        score=100,
        subscores={
            "requirements": 100,
            "architecture": 100,
            "security": 100,
            "testing": 100,
            "implementation": 100,
            "rag_grounding": 100,
        },
        reason="validated evidence satisfies acceptance checks",
        confidence=1,
    )
    return {
        "run_id": run_id,
        "implementation": implementation,
        "review": review,
        "tool_results": [],
        "errors": [],
        "final_status": "APPROVED",
        "route_history": [],
        "iteration": 1,
        "model_usage": [],
        "human_review_required": False,
    }


def test_run_on_project_delivers_when_confirmed_approved_and_backend_gh(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app" / "models").mkdir(parents=True)
    (project / "app" / "models" / "product.py").write_text(
        "class Product:\n    name: str\n", encoding="utf-8"
    )

    state = _approved_state()
    trace = SimpleNamespace(trace_id="trace-1", live=False)
    monkeypatch.setattr(
        "engineering_team.apply_run.execute_on_project",
        lambda *a, **k: (state, trace, 0.01, False),
    )

    pushed: list[Proposal] = []
    opened: list[Proposal] = []

    class FakeGitDelivery:
        def push(self, repository, proposal, *, confirmed):
            assert confirmed is True
            pushed.append(proposal)
            return proposal.branch

    class FakeBackend:
        def open(self, repository, proposal, *, confirmed):
            assert confirmed is True
            opened.append(proposal)
            return "https://example.test/pr/1"

    monkeypatch.setattr("engineering_team.apply_run.GitDelivery", FakeGitDelivery)
    monkeypatch.setattr(
        "engineering_team.apply_run.build_delivery", lambda settings: FakeBackend()
    )

    evidence = run_on_project(
        Settings(delivery_backend="gh"),
        project_path=project,
        specification="add sku",
        authorize_writes=True,
        confirm_delivery=True,
    )

    assert len(pushed) == 1
    assert len(opened) == 1
    assert "app/models/product.py" in pushed[0].updates
    assert evidence["delivery_branch"].startswith("aset/")
    assert evidence["delivery_pr_url"] == "https://example.test/pr/1"
    assert "delivery_error" not in evidence


def test_run_on_project_skips_delivery_without_confirm(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")

    state = _approved_state()
    # Ensure file_contents path exists so a proposal could be built if delivery ran.
    state["implementation"] = ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=["app.py"],
        diff="x = 2",
        evidence=["mcp://repository/update_file"],
        validation_result="ok",
        security_surface_changed=False,
        file_contents={"app.py": "x = 2\n"},
    )
    trace = SimpleNamespace(trace_id="trace-2", live=False)
    monkeypatch.setattr(
        "engineering_team.apply_run.execute_on_project",
        lambda *a, **k: (state, trace, 0.01, False),
    )

    called = {"push": 0}

    class FakeGitDelivery:
        def push(self, *a, **k):
            called["push"] += 1
            raise AssertionError("push must not run without confirm_delivery")

    monkeypatch.setattr("engineering_team.apply_run.GitDelivery", FakeGitDelivery)
    monkeypatch.setattr(
        "engineering_team.apply_run.build_delivery",
        lambda settings: MagicMock(open=MagicMock(return_value="https://x")),
    )

    evidence = run_on_project(
        Settings(delivery_backend="gh"),
        project_path=project,
        specification="change",
        authorize_writes=True,
        confirm_delivery=False,
    )

    assert called["push"] == 0
    assert "delivery_branch" not in evidence
    assert "delivery_pr_url" not in evidence

def test_run_on_project_records_delivery_refused(tmp_path, monkeypatch) -> None:
    """DeliveryRefused must not crash the report — land in evidence instead."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")

    state = _approved_state()
    state["implementation"] = ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=["app.py"],
        diff="x = 2",
        evidence=["mcp://repository/update_file"],
        validation_result="ok",
        security_surface_changed=False,
        file_contents={"app.py": "x = 2\n"},
    )
    trace = SimpleNamespace(trace_id="trace-3", live=False)
    monkeypatch.setattr(
        "engineering_team.apply_run.execute_on_project",
        lambda *a, **k: (state, trace, 0.01, False),
    )

    from engineering_team.delivery import DeliveryRefused

    class FakeGitDelivery:
        def push(self, *a, **k):
            raise DeliveryRefused("simulated refusal")

    monkeypatch.setattr("engineering_team.apply_run.GitDelivery", FakeGitDelivery)
    monkeypatch.setattr(
        "engineering_team.apply_run.build_delivery",
        lambda settings: MagicMock(open=MagicMock(return_value="https://x")),
    )

    evidence = run_on_project(
        Settings(delivery_backend="gh"),
        project_path=project,
        specification="change",
        authorize_writes=True,
        confirm_delivery=True,
    )

    assert evidence["delivery_error"] == "simulated refusal"
    assert "delivery_branch" not in evidence
    assert "delivery_pr_url" not in evidence


def test_proposal_prefers_disk_content_over_file_contents(tmp_path) -> None:
    from engineering_team.apply_run import _proposal_from_implementation

    project = tmp_path / "project"
    project.mkdir()
    disk_body = "class Product:\n    sku: str\n    # on disk\n"
    (project / "product.py").write_text(disk_body, encoding="utf-8")
    implementation = ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=["product.py"],
        diff="sku",
        evidence=["mcp://repository/update_file"],
        validation_result="ok",
        security_surface_changed=False,
        file_contents={"product.py": "class Product:\n    sku: str\n"},
    )
    review = ReviewerDecision(
        status=ReviewerStatus.APPROVED,
        score=100,
        subscores={
            "requirements": 100,
            "architecture": 100,
            "security": 100,
            "testing": 100,
            "implementation": 100,
            "rag_grounding": 100,
        },
        reason="ok",
        confidence=1,
    )
    proposal = _proposal_from_implementation(
        project_root=project,
        run_id="apply-disk-1",
        implementation=implementation,
        review=review,
        written_paths=["product.py"],
    )
    assert proposal is not None
    assert proposal.updates["product.py"] == disk_body
    assert proposal.files == {}

