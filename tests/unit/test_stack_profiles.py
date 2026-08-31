"""A profile names an image and the commands for one ecosystem (ADR 3, ADR 4)."""

from __future__ import annotations

import dataclasses

import pytest

from engineering_team.components import detect_components
from engineering_team.stacks import PROFILES, StackProfile, profile_for


def test_every_detectable_stack_has_a_profile() -> None:
    """Detection and execution must not disagree about what exists."""
    stacks = {"python", "jvm", "dotnet", "node"}
    assert set(PROFILES) == stacks


def test_the_python_profile_reproduces_todays_commands() -> None:
    """Behaviour-preserving: this is what QualityMCP runs before any of this."""
    python = profile_for("python")
    assert python.test_command("/env/bin/python") == [
        "/env/bin/python", "-I", "-m", "pytest",
    ]
    assert python.build_command("/env/bin/python") == [
        "/env/bin/python", "-I", "-m", "compileall", ".",
    ]
    assert python.lint_command("/env/bin/python")[:5] == [
        "/env/bin/python", "-I", "-m", "ruff", "check",
    ]


def test_non_python_commands_do_not_go_through_an_interpreter() -> None:
    """`mvn test` is the command; there is no module to import."""
    assert profile_for("jvm").test_command("") == ["mvn", "-B", "-q", "test"]
    assert profile_for("dotnet").test_command("") == ["dotnet", "test", "--nologo"]
    assert profile_for("node").test_command("") == ["npm", "test", "--silent"]


def test_every_image_is_pinned_by_digest() -> None:
    """ADR 2: a tag is a different image tomorrow, and a run stops reproducing."""
    for name, profile in PROFILES.items():
        assert "@sha256:" in profile.image, f"{name} image is not pinned"


def test_a_profile_serves_the_manifests_detection_looks_for() -> None:
    """Otherwise a component is found that nothing knows how to build."""
    for path, expected in (
        ("svc/pom.xml", "jvm"),
        ("api/App.csproj", "dotnet"),
        ("web/package.json", "node"),
        ("lib/pyproject.toml", "python"),
    ):
        (component,) = detect_components([path])
        assert profile_for(component.stack).name == expected


def test_an_unknown_stack_is_refused_rather_than_guessed() -> None:
    with pytest.raises(KeyError, match="cobol"):
        profile_for("cobol")


def test_profiles_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile_for("python").name = "other"  # type: ignore[misc]


def test_a_profile_declares_whether_it_needs_a_dependency_install() -> None:
    """Maven and dotnet resolve their own dependencies; npm and pip do not."""
    assert profile_for("node").install_command("") == ["npm", "ci"]
    assert profile_for("jvm").install_command("") is None
    assert profile_for("dotnet").install_command("") is None
    assert isinstance(profile_for("python"), StackProfile)
