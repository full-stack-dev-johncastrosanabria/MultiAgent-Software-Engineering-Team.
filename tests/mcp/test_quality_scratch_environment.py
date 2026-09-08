"""D2 fp-quality-env-nonpython: scratch for every profile; venv only for python.

prepare_environment used to be the only way to create the sandbox directory,
so jvm/node hit `quality environment has not been created` before any tool ran.
Direction 3 separates (a) scratch HOME/TMPDIR for all profiles from (b) a
Python venv layered on top for python only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.runner import ProcessRunner
from engineering_team.stacks import profile_for


def _stub_execute(self, args, *, cwd, deadline, allow_network=False,
                  allow_subprocesses=False, extra_env=None, writable_paths=()):
    return subprocess.CompletedProcess(list(args), 0, "ok", "")


def test_jvm_scan_dependencies_never_fails_for_missing_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ProcessRunner, "_execute_process", _stub_execute)
    monkeypatch.setattr(
        ProcessRunner, "_environment_root", staticmethod(lambda: tmp_path / "envs")
    )
    (tmp_path / "envs").mkdir()
    runner = ProcessRunner(tmp_path)
    quality = QualityMCP(
        tmp_path, runner=runner, profile=profile_for("jvm"), component="order-ms"
    )

    result = quality.scan_dependencies(AgentRole.SECURITY)

    assert "quality environment has not been created" not in (result.error or "")
    assert result.status is ToolStatus.SUCCESS
    assert runner.environment is not None
    assert not (runner.environment / "bin" / "python").exists()
    assert not (runner.environment / "pyvenv.cfg").exists()


def test_node_scan_dependencies_never_fails_for_missing_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ProcessRunner, "_execute_process", _stub_execute)
    monkeypatch.setattr(
        ProcessRunner, "_environment_root", staticmethod(lambda: tmp_path / "envs")
    )
    (tmp_path / "envs").mkdir()
    runner = ProcessRunner(tmp_path)
    quality = QualityMCP(
        tmp_path, runner=runner, profile=profile_for("node"), component="frontend"
    )

    result = quality.scan_dependencies(AgentRole.SECURITY)

    assert "quality environment has not been created" not in (result.error or "")
    assert result.status is ToolStatus.SUCCESS
    assert runner.environment is not None
    assert not (runner.environment / "bin" / "python").exists()


def test_python_scan_dependencies_still_builds_a_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def execute(self, args, *, cwd, deadline, allow_network=False,
                allow_subprocesses=False, extra_env=None, writable_paths=()):
        return subprocess.CompletedProcess(list(args), 0, "No broken requirements found.", "")

    monkeypatch.setattr(ProcessRunner, "_execute_process", execute)
    monkeypatch.setattr(
        ProcessRunner, "_environment_root", staticmethod(lambda: tmp_path / "envs")
    )
    (tmp_path / "envs").mkdir()

    def prepare_environment(self, deadline: float) -> str:
        directory = self.prepare_scratch()
        (directory / "bin").mkdir(exist_ok=True)
        (directory / "pyvenv.cfg").write_text("home = /usr" + "\n", encoding="utf-8")
        interp = directory / "bin" / "python"
        interp.write_text("#!/bin/sh" + "\n", encoding="utf-8")
        return str(interp)

    monkeypatch.setattr(ProcessRunner, "prepare_environment", prepare_environment)
    runner = ProcessRunner(tmp_path)
    quality = QualityMCP(tmp_path, runner=runner, profile=profile_for("python"))

    result = quality.scan_dependencies(AgentRole.SECURITY)

    assert "quality environment has not been created" not in (result.error or "")
    assert runner.environment is not None
    assert (runner.environment / "pyvenv.cfg").exists()


def test_jvm_scratch_directory_has_no_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ProcessRunner, "_execute_process", _stub_execute)
    monkeypatch.setattr(
        ProcessRunner, "_environment_root", staticmethod(lambda: tmp_path / "envs")
    )
    (tmp_path / "envs").mkdir()
    runner = ProcessRunner(tmp_path)
    quality = QualityMCP(tmp_path, runner=runner, profile=profile_for("jvm"))

    quality.scan_dependencies(AgentRole.SECURITY)

    env = runner.environment
    assert env is not None
    assert list(env.glob("**/pyvenv.cfg")) == []
    assert not (env / "bin" / "python").exists()
