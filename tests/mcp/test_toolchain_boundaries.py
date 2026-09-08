"""Two things a run should be able to say about the boundary it executed on.

Which JDK actually ran, and whether the boundary could host the suite at all.
The multistack series could answer neither: Maven resolved whatever the rebuilt
PATH offered, and a Testcontainers suite spent three runs failing on an image
pull that was never going to succeed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp import runner as runner_module
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.runner import ProcessRunner, _readable_java_home
from engineering_team.stacks import profile_for


def _jdk(root: Path) -> Path:
    home = root / "jdk"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "java").write_text("#!/bin/sh\n")
    return home


def test_a_readable_jdk_reaches_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _jdk(tmp_path)
    monkeypatch.setenv("JAVA_HOME", str(home))
    # pytest's own temporary root is one of the roots the sandbox denies, so
    # without this the fixture would exercise the exclusion rather than the
    # passthrough. A real JDK lives in a system location, not under /tmp.
    monkeypatch.setattr(runner_module, "_temporary_path_roots", lambda: ())
    runner = ProcessRunner(tmp_path / "workspace")
    monkeypatch.setattr(
        ProcessRunner, "_environment_root", staticmethod(lambda: tmp_path / "envs")
    )
    (tmp_path / "envs").mkdir()
    runner.prepare_scratch()

    environment = runner._subprocess_environment()

    assert environment["JAVA_HOME"] == str(home)
    assert environment["PATH"].startswith(str(home / "bin"))


def test_a_jdk_the_sandbox_cannot_read_is_not_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming an unreadable JDK trades a reporting gap for a broken toolchain.

    The sandbox denies reads under HOME, so a per-user version manager's JDK
    would be handed to Maven and then refused. Better to run what the rebuilt
    PATH offers and say nothing than to name something the command cannot open.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(runner_module, "_temporary_path_roots", lambda: ())
    monkeypatch.setenv("JAVA_HOME", str(_jdk(home / ".sdkman")))

    assert _readable_java_home() is None


def test_an_absent_or_broken_java_home_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("JAVA_HOME", raising=False)
    assert _readable_java_home() is None

    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "not-a-jdk"))
    assert _readable_java_home() is None

    empty = tmp_path / "no-binary"
    empty.mkdir()
    monkeypatch.setenv("JAVA_HOME", str(empty))
    assert _readable_java_home() is None


def _component(marker: str, manifest: str = "pom.xml") -> Path:
    root = Path(tempfile.mkdtemp())
    (root / manifest).write_text(marker, encoding="utf-8")
    return root


def test_a_testcontainers_suite_is_refused_before_the_run_not_during(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three trials read the same pull failure as a flake.

    `ContainerFetchException` after minutes of work names neither the cause nor
    the remedy. The refusal has to arrive before the work, and say where the
    suite does run.
    """
    root = _component("<project>org.testcontainers</project>")
    quality = QualityMCP(
        root,
        runner=ContainerRunner(root, image=profile_for("jvm").image),
        profile=profile_for("jvm"),
        component="order-ms",
    )

    result = quality.run_tests(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert result.duration_ms == 0
    assert "quality_runner=process" in (result.error or "")
    assert "ADR 10" in (result.error or "")


def test_the_same_component_is_not_refused_on_the_process_sandbox() -> None:
    root = _component("<project>org.testcontainers</project>")
    quality = QualityMCP(root, runner=ProcessRunner(root), profile=profile_for("jvm"))

    assert quality._container_api_refusal() is None


def test_a_component_that_starts_no_containers_still_runs_in_one() -> None:
    root = _component("<project/>")
    quality = QualityMCP(
        root,
        runner=ContainerRunner(root, image=profile_for("jvm").image),
        profile=profile_for("jvm"),
    )

    assert quality._container_api_refusal() is None
