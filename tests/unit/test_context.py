import pytest

from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    ReviewerStatus,
    RouteTarget,
    ToolStatus,
)
from engineering_team.contracts.models import (
    ImplementationResult,
    ReviewerDecision,
    ToolResult,
)
from engineering_team.contracts.state import EngineeringState
from engineering_team.models.context import build_context

AUTHORED_SOURCE = (
    "def autenticar(conexion, email, password):\n"
    "    return verificar_password(password)\n"
)


def test_product_context_excludes_repository_and_secrets() -> None:
    state = EngineeringState(run_id="r1", requirement="feature", repository_context={"secret": "x"})
    envelope = build_context(AgentRole.PRODUCT, state, "analyze")

    assert envelope.state_projection == {"run_id": "r1", "requirement": "feature"}


def test_context_rejects_unknown_fields() -> None:
    state = EngineeringState(run_id="r1", requirement="feature")
    with pytest.raises(ValueError):
        build_context(AgentRole.PRODUCT, state, "analyze", extra_projection={"secret": "x"})


def test_remediation_receives_bounded_failure_details_without_testing_tool_access():
    state = EngineeringState(run_id="r1", requirement="recovery",
        remediation_request="failed tests require implementation remediation",
        review=ReviewerDecision(status=ReviewerStatus.REJECTED, score=40,
            subscores={"testing": 0},
            reason="failed tests require implementation remediation", confidence=1,
            return_to=RouteTarget.DEVELOPER,
            problems=["large log " * 1500 + "\nTypeError: can't compare offset-naive and offset-aware datetimes\nbanca/auth.py:94"]))
    developer = build_context(AgentRole.DEVELOPER, state, "fix")
    assert "TypeError" in developer.remediation_feedback
    assert "banca/auth.py:94" in developer.remediation_feedback
    assert len(developer.remediation_feedback) < 6500
    assert "run_tests" not in developer.allowed_tools
    product = build_context(AgentRole.PRODUCT, state, "analyze")
    assert "TypeError" not in product.remediation_feedback


def test_remediation_redacts_secrets_before_truncating_diagnostics() -> None:
    secret = "s" * 2100
    state = EngineeringState(
        run_id="r1",
        requirement="recovery",
        remediation_request="failed tests require implementation remediation",
        review=ReviewerDecision(
            status=ReviewerStatus.REJECTED,
            score=40,
            subscores={"testing": 0},
            reason="failed tests require implementation remediation",
            confidence=1,
            return_to=RouteTarget.DEVELOPER,
            problems=[f"AssertionError: password={secret}"],
        ),
    )

    developer = build_context(AgentRole.DEVELOPER, state, "fix")

    assert "[REDACTED]" in developer.remediation_feedback
    assert secret[-2000:] not in developer.remediation_feedback


def test_remediation_redacts_quoted_and_mapping_secret_values() -> None:
    state = EngineeringState(
        run_id="r1",
        requirement="recovery",
        remediation_request="failed tests require implementation remediation",
        review=ReviewerDecision(
            status=ReviewerStatus.REJECTED,
            score=40,
            subscores={"testing": 0},
            reason="failed tests require implementation remediation",
            confidence=1,
            return_to=RouteTarget.DEVELOPER,
            problems=[
                'AssertionError: password="alpha beta gamma"',
                "AssertionError: {'password': 'delta epsilon zeta'}",
            ],
        ),
    )

    feedback = build_context(AgentRole.DEVELOPER, state, "fix").remediation_feedback

    assert "alpha beta gamma" not in feedback
    assert "delta epsilon zeta" not in feedback
    assert feedback.count("[REDACTED]") == 2


def test_total_remediation_feedback_is_bounded_to_six_kib() -> None:
    state = EngineeringState(
        run_id="r1",
        requirement="recovery",
        remediation_request="reason " * 300,
        review=ReviewerDecision(
            status=ReviewerStatus.REJECTED,
            score=40,
            subscores={"testing": 0},
            reason="failed tests require implementation remediation",
            confidence=1,
            return_to=RouteTarget.DEVELOPER,
            problems=[f"diagnostic-{index}: {'x' * 2100}" for index in range(8)],
        ),
    )

    feedback = build_context(AgentRole.DEVELOPER, state, "fix").remediation_feedback

    assert len(feedback.encode()) <= 6 * 1024


def test_developer_excludes_results_produced_for_testing_role() -> None:
    state = EngineeringState(
        run_id="r1",
        requirement="fix build",
        tool_results=[
            ToolResult(
                tool_name="run_build",
                allowed_role=AgentRole.TESTING,
                status=ToolStatus.FAIL,
                input_summary="testing build",
                output_summary="complete testing output must stay isolated",
                duration_ms=1,
            ),
            ToolResult(
                tool_name="run_build",
                allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS,
                input_summary="developer build",
                output_summary="developer-owned result",
                duration_ms=1,
            ),
        ],
    )

    envelope = build_context(AgentRole.DEVELOPER, state, "fix")

    assert [item.output_summary for item in envelope.tool_results] == [
        "developer-owned result"
    ]


def _remediation_state() -> EngineeringState:
    """A run on its second pass: the Developer proposed code and was sent back."""
    return EngineeringState(
        run_id="r1",
        requirement="add password recovery to banca/auth.py",
        implementation=ImplementationResult(
            action_mode=ActionMode.PROPOSED,
            changed_files=["banca/auth.py"],
            diff="--- a/banca/auth.py\n+++ b/banca/auth.py\n+def recuperar_password(): ...",
            evidence=["banca/auth.py"],
            validation_result="pytest: 1 failed",
            file_contents={"banca/auth.py": AUTHORED_SOURCE},
        ),
        remediation_request="failed tests require implementation remediation",
        review=ReviewerDecision(
            status=ReviewerStatus.REJECTED, score=40, subscores={"testing": 0},
            reason="failed tests require implementation remediation", confidence=1,
            return_to=RouteTarget.DEVELOPER,
            problems=["ImportError: cannot import name 'encriptar_password'"],
        ),
    )


def test_developer_projection_carries_the_implementation_it_authored() -> None:
    """Finding 7: the only role that writes was the only one blind to its own output.

    Every downstream role receives `implementation`; the Developer did not, so a
    remediation cycle started from nothing instead of repairing what was there.
    """
    envelope = build_context(AgentRole.DEVELOPER, _remediation_state(), "fix")

    assert "implementation" in envelope.state_projection
    assert envelope.state_projection["implementation"] is not None
