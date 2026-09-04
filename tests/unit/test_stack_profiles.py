"""A profile names an image and the commands for one ecosystem (ADR 3, ADR 4)."""

from __future__ import annotations

import dataclasses

import pytest

from engineering_team.components import detect_components
from engineering_team.stacks import PROFILES, StackProfile, profile_for


def test_every_detectable_stack_has_a_profile() -> None:
    """Detection and execution must not disagree about what exists.

    Derived from detection rather than restated: a hardcoded list drifts the
    moment a manifest is added, and then says nothing.
    """
    from engineering_team.components import _MANIFEST_NAMES, _MANIFEST_SUFFIXES

    detectable = set(_MANIFEST_NAMES.values()) | set(_MANIFEST_SUFFIXES.values())
    assert detectable == set(PROFILES)


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
    assert python.dependency_command("/env/bin/python") == [
        "/env/bin/python", "-I", "-m", "pip", "check",
    ]
    assert python.security_command("/env/bin/python") == [
        "/env/bin/python", "-I", "-m", "ruff", "check",
    ]


def test_every_detectable_profile_declares_both_security_operations() -> None:
    for name, profile in PROFILES.items():
        interpreter = "/env/bin/python" if name == "python" else ""
        assert profile.dependency_command(interpreter, "/aset/env"), name
        assert profile.security_command(interpreter, "/aset/env"), name


def test_jvm_security_operations_are_pinned_maven_commands() -> None:
    jvm = profile_for("jvm")
    commands = (
        jvm.dependency_command("", "/aset/env"),
        jvm.security_command("", "/aset/env"),
    )

    assert all(command is not None and command[0] == "mvn" for command in commands)
    assert not any("python" in part for command in commands for part in command or ())
    security = commands[1] or []
    assert any(
        part.startswith("org.owasp:dependency-check-maven:")
        and part.endswith(":check")
        and "LATEST" not in part
        for part in security
    )


def test_native_security_commands_match_the_approved_toolchains() -> None:
    assert profile_for("node").dependency_command("", "/aset/env") == [
        "npm", "ls", "--all",
    ]
    assert profile_for("node").security_command("", "/aset/env") == [
        "npm", "audit", "--omit=dev", "--audit-level=high",
    ]
    assert profile_for("dotnet").dependency_command("", "/aset/env")[:4] == [
        "dotnet", "list", "package", "--include-transitive",
    ]
    assert profile_for("dotnet").security_command("", "/aset/env")[:5] == [
        "dotnet", "list", "package", "--include-transitive", "--vulnerable",
    ]
    assert profile_for("go").dependency_command("", "/aset/env") == [
        "go", "list", "-m", "all",
    ]
    go_security = profile_for("go").security_command("", "/aset/env") or []
    assert go_security[:2] == ["go", "run"]
    assert "@v" in go_security[2]
    assert go_security[-1] == "./..."


def test_scan_network_policy_is_explicit_for_every_profile() -> None:
    expected = {
        "python": (False, False),
        "jvm": (True, True),
        "node": (False, True),
        "dotnet": (True, True),
        "go": (True, True),
    }

    assert {
        name: (
            profile.dependency_needs_network,
            profile.security_needs_network,
        )
        for name, profile in PROFILES.items()
    } == expected


def test_non_python_commands_do_not_go_through_an_interpreter() -> None:
    """`mvn test` is the command; there is no module to import."""
    for stack in ("jvm", "dotnet", "node"):
        command = profile_for(stack).test_command("", "/aset/env")
        assert "{interpreter}" not in " ".join(command)
    assert profile_for("jvm").test_command("", "/aset/env")[0] == "mvn"
    assert profile_for("dotnet").test_command("", "/aset/env")[0] == "dotnet"
    assert profile_for("node").test_command("", "/aset/env") == ["npm", "test", "--silent"]


def test_toolchain_caches_are_placed_on_the_shared_volume() -> None:
    """Each command is a fresh container whose HOME it cannot write.

    Measured, not assumed: without a writable cache Maven reports it cannot write
    to /root/.m2 and the run fails.
    """
    assert "-Dmaven.repo.local=/aset/env/m2" in profile_for("jvm").test_command(
        "", "/aset/env"
    )
    jvm = profile_for("jvm")
    assert "-Dmaven.repo.local=/aset/env/m2" in (
        jvm.dependency_command("", "/aset/env") or []
    )
    assert "-DdataDirectory=/aset/env/dependency-check" in (
        jvm.security_command("", "/aset/env") or []
    )
    assert any(
        "DependencyCheck_Builder/nvd_cache/nvdcve-{0}.json.gz" in part
        for part in (jvm.security_command("", "/aset/env") or [])
    )
    assert dict(jvm.env("/aset/env"))["HOME"] == "/aset/env/home"
    assert "-p:RestorePackagesPath=/aset/env/nuget" in profile_for(
        "dotnet"
    ).test_command("", "/aset/env")
    assert dict(profile_for("dotnet").env("/aset/env"))["NUGET_PACKAGES"] == (
        "/aset/env/nuget"
    )
    assert profile_for("node").install_command("", "/aset/env") == [
        "npm", "ci", "--cache", "/aset/env/npm",
    ]
    assert dict(profile_for("node").env("/aset/env"))["npm_config_cache"] == (
        "/aset/env/npm"
    )
    assert dict(profile_for("go").env("/aset/env"))["GOMODCACHE"] == (
        "/aset/env/gomod"
    )


def test_only_python_tests_run_offline() -> None:
    """A difference worth stating rather than hiding.

    `dependency:go-offline` completes and a following offline `mvn test` still
    fails, so a restore phase cannot honestly promise an offline test phase for
    these ecosystems.
    """
    assert profile_for("python").test_needs_network is False
    for stack in ("jvm", "dotnet", "node", "go"):
        assert profile_for(stack).test_needs_network is True


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
    assert profile_for("node").install_command("", "/aset/env")[:2] == ["npm", "ci"]
    assert profile_for("jvm").install_command("", "/aset/env") is None
    assert profile_for("dotnet").install_command("", "/aset/env") is None
    assert isinstance(profile_for("python"), StackProfile)
