"""Starting a database creates no tables.

ADR 5 starts what a project declares and stops there. InterviewCleanApi met a
MySQL service that had come up perfectly and failed ten of sixteen tests on
missing tables, which reads as a broken suite rather than an unprepared schema.
The step between the two belongs to the run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engineering_team.components import migration_projects
from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.runner import ProcessRunner
from engineering_team.stacks import profile_for


def _dotnet_tree() -> list[str]:
    return [
        "Api/Api.csproj",
        "Api/Program.cs",
        "Api/appsettings.json",
        "Infra/Infra.csproj",
        "Infra/Migrations/20260318_InitialCreate.Designer.cs",
        "Infra/Migrations/20260318_InitialCreate.cs",
        "Tests/Tests.csproj",
    ]


def test_the_two_projects_a_migration_needs_are_found_by_path() -> None:
    assert migration_projects(_dotnet_tree()) == ("Infra/Infra.csproj", "Api/Api.csproj")


def test_a_project_without_migrations_is_not_migrated() -> None:
    assert migration_projects(["Api/Api.csproj", "Api/Program.cs"]) is None


def test_ambiguity_is_not_resolved_by_guessing() -> None:
    """Two startup projects is a question, and migrating one of them is an answer
    nobody gave. The run applies no schema rather than picking."""
    tree = [*_dotnet_tree(), "Worker/Worker.csproj", "Worker/Program.cs"]

    assert migration_projects(tree) is None


def test_a_vendored_copy_is_not_a_migration_project() -> None:
    tree = [
        "node_modules/pkg/Api/Api.csproj",
        "node_modules/pkg/Api/Program.cs",
        "node_modules/pkg/Infra/Infra.csproj",
        "node_modules/pkg/Infra/Migrations/X.Designer.cs",
    ]

    assert migration_projects(tree) is None


def test_the_toolchain_says_how_it_applies_a_schema() -> None:
    tool, apply = profile_for("dotnet").schema_commands(
        "/env", "Infra/Infra.csproj", "Api/Api.csproj"
    )

    assert tool == [
        "dotnet", "tool", "update", "dotnet-ef", "--tool-path", "/env/tools",
    ]
    assert apply == [
        "/env/tools/dotnet-ef", "database", "update",
        "--project", "Infra/Infra.csproj",
        "--startup-project", "Api/Api.csproj",
    ]


def test_a_stack_with_no_migration_command_applies_none() -> None:
    assert profile_for("jvm").schema_commands("/env", "a", "b") == []
    assert profile_for("python").schema_commands("/env", "a", "b") == []


def _project(tmp_path: Path) -> Path:
    for name in _dotnet_tree():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return tmp_path


def test_a_schema_that_will_not_apply_is_infrastructure_not_a_failing_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Routing this to the Developer would ask someone to fix code that is fine.

    Finding 7 is the shape: an infrastructure problem wearing a test failure's
    clothes sends the next cycle after the wrong thing.
    """
    root = _project(tmp_path)
    quality = QualityMCP(root, runner=ProcessRunner(root), profile=profile_for("dotnet"))
    monkeypatch.setattr(
        QualityMCP,
        "_execute_process",
        lambda self, args, **kwargs: subprocess.CompletedProcess(
            args, 1, "", "Unable to create a DbContext"
        ),
    )
    try:
        result = quality._apply_schema(AgentRole.TESTING, "run_tests", 0.0)

        assert result is not None
        assert result.status is ToolStatus.UNAVAILABLE
        assert "migrations failed" in (result.error or "")
        assert "INFRASTRUCTURE_ERROR" in (result.error or "")
    finally:
        quality.close()


def test_every_declared_command_runs_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    quality = QualityMCP(root, runner=ProcessRunner(root), profile=profile_for("dotnet"))
    seen: list[list[str]] = []

    def record(self, args, **kwargs):
        seen.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(QualityMCP, "_execute_process", record)
    try:
        assert quality._apply_schema(AgentRole.TESTING, "run_tests", 0.0) is None

        assert seen[0][:2] == ["dotnet", "tool"]
        assert seen[1][1:3] == ["database", "update"]
    finally:
        quality.close()


def test_a_stack_without_migrations_does_no_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    quality = QualityMCP(root, runner=ProcessRunner(root), profile=profile_for("jvm"))
    monkeypatch.setattr(
        QualityMCP,
        "_execute_process",
        lambda *a, **k: pytest.fail("a stack with no migration command ran one"),
    )
    try:
        assert quality._apply_schema(AgentRole.TESTING, "run_tests", 0.0) is None
    finally:
        quality.close()


class _Services:
    """Enough of ServiceStack to answer the two questions the gate asks it."""

    services = ("mysql",)
    network = None

    def __init__(self) -> None:
        self.up_called_at: list[str] = []

    def up(self, deadline: float) -> None:
        self.up_called_at.append("up")


def test_the_schema_is_applied_after_the_services_and_before_any_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order is the whole point.

    Before the services there is no database to migrate, and the connection
    string the command needs is the one they publish.
    """
    root = _project(tmp_path)
    services = _Services()
    quality = QualityMCP(
        root, runner=ProcessRunner(root), profile=profile_for("dotnet"),
        services=services,
    )
    order: list[str] = []
    monkeypatch.setattr(
        QualityMCP,
        "_apply_schema",
        lambda self, *a, **k: order.append("schema") or None,
    )
    try:
        assert quality._ensure_services(AgentRole.TESTING, "run_tests", 0.0) is None

        assert services.up_called_at == ["up"]
        assert order == ["schema"]
    finally:
        quality.close()


def test_a_project_that_declares_no_services_is_not_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No database was started, so there is nothing to bring up to date."""
    root = _project(tmp_path)
    quality = QualityMCP(root, runner=ProcessRunner(root), profile=profile_for("dotnet"))
    monkeypatch.setattr(
        QualityMCP,
        "_apply_schema",
        lambda *a, **k: pytest.fail("migrated a database nothing started"),
    )
    try:
        assert quality._ensure_services(AgentRole.TESTING, "run_tests", 0.0) is None
    finally:
        quality.close()
