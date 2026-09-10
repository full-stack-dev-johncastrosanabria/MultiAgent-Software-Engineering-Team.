"""Which of a component's tests the gate runs, when the boundary cannot host all.

InterviewCleanApi ships four Selenium tests alongside sixteen that need only a
database. Chrome resolves its user data directory through a macOS API that
ignores TMPDIR and lands in a root the sandbox denies, so every browser test
fails in a millisecond and the gate can never be green. Narrowing it is the
operator's decision, and one the run has to state rather than infer.
"""

from __future__ import annotations

from pathlib import Path

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.quality import QualityMCP
from engineering_team.stacks import profile_for


def test_a_stack_that_can_narrow_says_how() -> None:
    assert profile_for("dotnet").test_filter_arguments("A!~E2ETests") == [
        "--filter",
        "A!~E2ETests",
    ]
    assert profile_for("python").test_filter_arguments("not slow") == ["-k", "not slow"]


def test_no_filter_leaves_the_command_alone() -> None:
    assert profile_for("dotnet").test_filter_arguments("") == []


def test_a_stack_without_filter_syntax_refuses_before_running_anything(
    tmp_path: Path,
) -> None:
    """The one failure mode a narrowed gate must not have is running everything.

    Silently ignoring the request would report a green suite the operator never
    asked for, over tests the boundary cannot host. The refusal arrives before
    the work, like the Testcontainers one in ADR 10.
    """
    quality = QualityMCP(
        tmp_path, profile=profile_for("jvm"), test_filter="SomeExpression"
    )
    try:
        result = quality.run_tests(AgentRole.TESTING)

        assert result.status is ToolStatus.UNAVAILABLE
        assert result.duration_ms == 0
        assert "no test filter syntax" in (result.error or "")
    finally:
        quality.close()


def test_the_filter_reaches_quality_from_settings(tmp_path: Path) -> None:
    quality = QualityMCP(
        tmp_path,
        settings=Settings(
            quality_test_filter="FullyQualifiedName!~E2ETests",
            quality_stack="dotnet",
        ),
        profile=profile_for("dotnet"),
    )
    try:
        assert quality.test_filter == "FullyQualifiedName!~E2ETests"
    finally:
        quality.close()
