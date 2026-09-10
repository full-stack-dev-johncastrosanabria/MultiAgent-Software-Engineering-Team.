"""apply_run must pick the component profile, never a global python default.

Finding 19 / ADR 4: a Maven or .NET tree pointed at through run-project used to
inherit Settings.quality_stack="python" and fire pytest. Detection fans out per
component; an explicit QUALITY_STACK still wins (Flask).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engineering_team.apply_run import (
    open_project_quality,
    quality_selection_is_explicit,
    quality_targets_for,
)
from engineering_team.components import Component
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.mcp.client import MCPQualityClient
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.quality import CompositeQuality

PINNED = "python@sha256:" + "0" * 64


class _Recorder(ContainerRunner):
    """Records argv instead of running anything.

    It subclasses the boundary the gate really uses, so what argv this asserts
    on is what a container would have been handed. Nothing is executed, so the
    digest never has to resolve.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(root, image=PINNED)
        self.commands: list[list[str]] = []

    def require_available(self) -> None:
        return None

    def prepare_environment(self, deadline: float) -> str:
        return "/env/bin/python"

    def execute(self, request):
        self.commands.append(list(request.args))
        return subprocess.CompletedProcess(list(request.args), 0, "ok", "")


def _settings_without_quality_override() -> Settings:
    """Settings whose quality_stack was not chosen by the caller or env."""
    fresh = Settings()
    object.__setattr__(
        fresh,
        "__dict__",
        {**fresh.__dict__, "quality_stack": "python", "quality_component_path": ""},
    )
    fields_set = set(fresh.model_fields_set)
    fields_set.discard("quality_stack")
    fields_set.discard("quality_component_path")
    object.__setattr__(fresh, "__pydantic_fields_set__", fields_set)
    assert not quality_selection_is_explicit(fresh)
    return fresh


def _run_detected(tmp_path: Path) -> tuple[_Recorder, list[list[str]]]:
    recorder = _Recorder(tmp_path)
    with open_project_quality(
        tmp_path,
        _settings_without_quality_override(),
        timeout_seconds=30,
        runner=recorder,
    ) as quality:
        quality.run_tests(AgentRole.TESTING)
    return recorder, recorder.commands


def test_components_in_walks_a_real_tree(tmp_path: Path) -> None:
    from engineering_team.components import components_in

    (tmp_path / "order-ms").mkdir()
    (tmp_path / "order-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    (tmp_path / "node_modules" / "left-pad" / "package.json").write_text(
        "{}", encoding="utf-8"
    )
    found = components_in(tmp_path)
    assert {(c.path, c.stack) for c in found} == {
        ("order-ms", "jvm"),
        ("frontend", "node"),
    }


def test_maven_tree_runs_mvn_not_pytest(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    _, commands = _run_detected(tmp_path)
    assert commands, "no command reached the runner"
    assert commands[-1][0] == "mvn"
    assert commands[-1][-1] == "test"
    assert not any("pytest" in " ".join(c) for c in commands)


def test_dotnet_tree_runs_dotnet_test_not_pytest(tmp_path: Path) -> None:
    (tmp_path / "App.csproj").write_text("<Project/>", encoding="utf-8")
    _, commands = _run_detected(tmp_path)
    assert commands[-1][:2] == ["dotnet", "test"]
    assert not any("pytest" in " ".join(c) for c in commands)


def test_python_tree_still_uses_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )
    _, commands = _run_detected(tmp_path)
    assert any("pytest" in part for cmd in commands for part in cmd)


def test_multi_maven_and_node_never_invokes_pytest(tmp_path: Path) -> None:
    (tmp_path / "order-ms").mkdir()
    (tmp_path / "order-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "payment-ms").mkdir()
    (tmp_path / "payment-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    settings = _settings_without_quality_override()
    recorder = _Recorder(tmp_path)
    handle = open_project_quality(
        tmp_path, settings, timeout_seconds=30, runner=recorder
    )
    assert isinstance(handle, CompositeQuality)
    with handle as quality:
        quality.run_tests(AgentRole.TESTING)
    test_heads = [
        cmd[0] for cmd in recorder.commands if cmd and cmd[0] in {"mvn", "npm", "dotnet"}
    ]
    assert test_heads.count("mvn") >= 2
    assert "npm" in test_heads
    assert not any("pytest" in part for cmd in recorder.commands for part in cmd)


def _stack_flags_for(root: Path, settings: Settings, component) -> dict[str, str]:
    """The `--stack` / `--component-root` a detected component travels under.

    Since ADR 14 made the container the default, ``open_project_quality`` hands
    a container run to the infrastructure owner instead of the MCP subprocess,
    so the argv is no longer reachable through it. What these tests are about --
    that detection, not a global python default, decides the stack -- lives in
    the settings the dispatcher copies per component, and those are what the
    client turns into flags.
    """
    adjusted = settings.model_copy(
        update={
            "quality_stack": component.stack,
            "quality_component_path": component.path,
        }
    )
    args = MCPQualityClient(root, timeout_seconds=30, settings=adjusted)._parameters().args
    return {
        flag: args[args.index(flag) + 1]
        for flag in ("--stack", "--component-root")
        if flag in args
    }


def test_explicit_quality_stack_python_is_not_overridden_by_pom(tmp_path: Path) -> None:
    """Flask sets QUALITY_STACK=python; detection must not steal that choice."""
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    settings = Settings(quality_stack="python")
    assert quality_selection_is_explicit(settings)
    targets = quality_targets_for(settings, tmp_path)
    assert len(targets) == 1
    assert targets[0].stack == "python"
    assert _stack_flags_for(tmp_path, settings, targets[0])["--stack"] == "python"


def test_single_detected_jvm_component_keeps_mcp_stack_flags(tmp_path: Path) -> None:
    (tmp_path / "order-ms").mkdir()
    (tmp_path / "order-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    settings = _settings_without_quality_override()
    targets = quality_targets_for(settings, tmp_path)
    assert len(targets) == 1
    flags = _stack_flags_for(tmp_path, settings, targets[0])
    assert flags["--stack"] == "jvm"
    assert flags["--component-root"] == "order-ms"


def test_unknown_detected_stack_fails_closed(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    settings = _settings_without_quality_override()
    monkeypatch.setattr(
        "engineering_team.apply_run.components_in",
        lambda _root: [Component(path="", stack="cobol", manifest="pom.xml")],
    )
    with pytest.raises(KeyError, match="cobol"):
        quality_targets_for(settings, tmp_path)
