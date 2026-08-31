"""Which boundary a run executes behind is a decision, not an accident.

Auto-detection is deliberately absent. A runner that silently varies by machine
reproduces finding 5, where telemetry could not distinguish a primary path from a
fallback: the same run would be isolated differently depending on whether a
daemon happened to be up, and nothing would say so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_team.config import Settings
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.runner import ProcessRunner

PINNED = "python@sha256:" + "0" * 64


def test_the_process_sandbox_stays_the_default(tmp_path: Path) -> None:
    assert Settings().quality_runner == "process"
    assert isinstance(QualityMCP(tmp_path)._runner, ProcessRunner)


def test_configuring_a_container_runner_selects_it(tmp_path: Path) -> None:
    settings = Settings(quality_runner="container", quality_container_image=PINNED)
    quality = QualityMCP(tmp_path, settings=settings)
    assert isinstance(quality._runner, ContainerRunner)
    assert quality._runner.image == PINNED


def test_an_unknown_runner_fails_closed(tmp_path: Path) -> None:
    """Never silently fall back: an unreadable choice is a configuration error."""
    settings = Settings(quality_runner="firecracker")
    with pytest.raises(ValueError, match="firecracker"):
        QualityMCP(tmp_path, settings=settings)


def test_a_container_runner_without_an_image_fails_closed(tmp_path: Path) -> None:
    """Choosing containers without saying which image is not a runnable choice."""
    settings = Settings(quality_runner="container", quality_container_image="")
    with pytest.raises(ValueError, match="image"):
        QualityMCP(tmp_path, settings=settings)


def test_an_explicit_runner_argument_still_wins(tmp_path: Path) -> None:
    """Tests and callers that build their own runner are not overridden by config."""
    injected = ProcessRunner(tmp_path)
    settings = Settings(quality_runner="container", quality_container_image=PINNED)
    assert QualityMCP(tmp_path, runner=injected, settings=settings)._runner is injected


def test_the_served_backend_honours_configuration(tmp_path: Path, monkeypatch) -> None:
    """build_quality_server is the real construction site, so config lands there."""
    import engineering_team.mcp.server as server_module

    captured: dict[str, object] = {}
    real = server_module.QualityMCP

    def spy(root, **kwargs):
        captured.update(kwargs)
        return real(root, **kwargs)

    monkeypatch.setattr(server_module, "QualityMCP", spy)
    settings = Settings(quality_runner="container", quality_container_image=PINNED)
    server_module.build_quality_server(tmp_path, settings=settings)

    assert captured["settings"] is settings


# -- ADR 4: the commands come from the component's profile -------------------


class _Recorder(ProcessRunner):
    """A process runner that records argv instead of running anything."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.commands: list[list[str]] = []

    def require_available(self) -> None:
        return None

    def prepare_environment(self, deadline: float) -> str:
        return "/env/bin/python"

    def execute(self, request):
        import subprocess

        self.commands.append(list(request.args))
        return subprocess.CompletedProcess(list(request.args), 0, "ok", "")


def _last_command(quality: QualityMCP, recorder: _Recorder) -> list[str]:
    from engineering_team.contracts.enums import AgentRole

    quality.run_tests(AgentRole.TESTING)
    assert recorder.commands, "no command reached the runner"
    return recorder.commands[-1]


def test_a_node_component_runs_npm_not_pytest(tmp_path: Path) -> None:
    from engineering_team.stacks import profile_for

    recorder = _Recorder(tmp_path)
    quality = QualityMCP(tmp_path, runner=recorder, profile=profile_for("node"))
    assert _last_command(quality, recorder) == ["npm", "test", "--silent"]


def test_a_jvm_component_runs_maven_without_an_interpreter(tmp_path: Path) -> None:
    from engineering_team.stacks import profile_for

    recorder = _Recorder(tmp_path)
    quality = QualityMCP(tmp_path, runner=recorder, profile=profile_for("jvm"))
    command = _last_command(quality, recorder)
    assert command[0] == "mvn"
    assert command[-1] == "test"
    assert not any("python" in part for part in command)


def test_a_dotnet_component_runs_dotnet_test(tmp_path: Path) -> None:
    from engineering_team.stacks import profile_for

    recorder = _Recorder(tmp_path)
    quality = QualityMCP(tmp_path, runner=recorder, profile=profile_for("dotnet"))
    command = _last_command(quality, recorder)
    assert command[:3] == ["dotnet", "test", "--nologo"]


def test_python_remains_the_default_profile(tmp_path: Path) -> None:
    from engineering_team.stacks import profile_for

    assert QualityMCP(tmp_path).profile is profile_for("python")


# -- finding 3: nothing installs into the interpreter that is running us ------


def test_no_command_ever_runs_the_interpreter_this_process_uses(tmp_path: Path) -> None:
    """Finding 3 as written: `pip install .` against sys.executable left one
    project's dependencies available to the next, and let concurrent runs mutate
    the same environment. Every command now goes through an environment this
    QualityMCP built for itself."""
    import sys

    from engineering_team.contracts.enums import AgentRole

    recorder = _Recorder(tmp_path)
    quality = QualityMCP(tmp_path, runner=recorder)
    quality.run_tests(AgentRole.TESTING)

    for command in recorder.commands:
        assert sys.executable not in command, (
            f"a command reached the operator's interpreter: {command}"
        )


def test_the_environment_is_built_from_the_base_interpreter_not_the_current_one() -> None:
    """`sys._base_executable` is what allows HOME to be closed even when the MCP
    process itself was started from the operator's virtual environment."""
    import inspect

    from engineering_team.mcp.runner import ProcessRunner

    source = inspect.getsource(ProcessRunner._base_interpreter)
    assert "_base_executable" in source


def test_each_quality_instance_provisions_its_own_environment(tmp_path: Path) -> None:
    """Two runs must not share what one of them installed."""
    first = ProcessRunner(tmp_path / "a")
    second = ProcessRunner(tmp_path / "b")
    assert first.environment is None and second.environment is None
    first.environment = tmp_path / "env-a"
    assert second.environment is None, "environments are per runner, not global"


# -- the project's services come up before its tests run ---------------------


class _FakeStack:
    """A service stack that records whether it was asked to start."""

    def __init__(self, *, services=("postgres",), fails: bool = False) -> None:
        self.services = services
        self.network = None
        self.started = False
        self._fails = fails

    def up(self, deadline: float) -> None:
        from engineering_team.services import ServiceStartupError

        self.started = True
        if self._fails:
            raise ServiceStartupError("postgres never became ready")
        self.network = "aset-run_default"

    def down(self) -> None:
        self.network = None


def test_services_start_before_the_tests_that_need_them(tmp_path: Path) -> None:
    from engineering_team.contracts.enums import AgentRole

    stack = _FakeStack()
    recorder = _Recorder(tmp_path)
    quality = QualityMCP(tmp_path, runner=recorder, services=stack)
    quality.run_tests(AgentRole.TESTING)

    assert stack.started, "the tests ran without the database the project expects"


def test_a_service_that_never_starts_is_not_a_failing_test(tmp_path: Path) -> None:
    """Finding 7's misleading headline: infrastructure reported as bad code."""
    from engineering_team.contracts.enums import AgentRole, ToolStatus

    stack = _FakeStack(fails=True)
    recorder = _Recorder(tmp_path)
    quality = QualityMCP(tmp_path, runner=recorder, services=stack)
    result = quality.run_tests(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "INFRASTRUCTURE_ERROR" in (result.error or "")
    assert not recorder.commands, "no test should run without its dependencies"


def test_a_project_with_no_services_is_unaffected(tmp_path: Path) -> None:
    from engineering_team.contracts.enums import AgentRole

    stack = _FakeStack(services=())
    recorder = _Recorder(tmp_path)
    QualityMCP(tmp_path, runner=recorder, services=stack).run_tests(AgentRole.TESTING)
    assert recorder.commands, "the tests should still have run"


# -- finding 10: a project declares its dependencies somewhere ---------------


def _pip_installs(commands: list[list[str]]) -> list[list[str]]:
    return [c for c in commands if "pip" in " ".join(c) and "install" in c]


def test_a_project_with_only_requirements_txt_gets_its_dependencies(tmp_path: Path) -> None:
    """Measured against FlaskApiProduct: no pyproject.toml, so the environment
    was left empty, every test died with ModuleNotFoundError: No module named
    'flask', and the Reviewer looped the Developer three times over a problem
    that had nothing to do with the code."""
    from engineering_team.contracts.enums import AgentRole

    (tmp_path / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
    recorder = _Recorder(tmp_path)
    QualityMCP(tmp_path, runner=recorder).run_tests(AgentRole.TESTING)

    installs = _pip_installs(recorder.commands)
    assert installs, "the project's dependencies were never installed"
    assert any("requirements.txt" in " ".join(c) for c in installs), installs


def test_detection_and_installation_agree_about_what_a_python_project_is() -> None:
    """components.py already treats requirements.txt as a Python manifest.
    Installation knowing a narrower set is how the gap appeared."""
    from engineering_team.components import _MANIFEST_NAMES
    from engineering_team.mcp.quality import PROJECT_MANIFESTS

    python_manifests = {
        name for name, stack in _MANIFEST_NAMES.items() if stack == "python"
    }
    assert python_manifests <= set(PROJECT_MANIFESTS)


def test_a_project_with_no_manifest_at_all_still_runs(tmp_path: Path) -> None:
    """Nothing to install is not a failure."""
    from engineering_team.contracts.enums import AgentRole

    recorder = _Recorder(tmp_path)
    QualityMCP(tmp_path, runner=recorder).run_tests(AgentRole.TESTING)
    assert recorder.commands, "the suite should still have been attempted"
