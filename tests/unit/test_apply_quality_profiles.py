"""Apply-run quality must pick the component profile, never a global pytest."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engineering_team.apply_run import (
    open_project_quality,
    quality_selection_is_explicit,
    quality_targets_for,
)
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.mcp.quality import CompositeQuality
from engineering_team.mcp.runner import CommandRequest


class FakeRunner:
    """Record argv instead of executing anything."""

    def __init__(self) -> None:
        self.requests: list[CommandRequest] = []
        self.environment: Path | None = None
        self.closed = False

    def require_available(self) -> None:
        return None

    def prepare_environment(self, deadline: float) -> str:
        self.environment = Path("/fake/env")
        return "/fake/env/bin/python"

    @property
    def closing(self) -> bool:
        return self.closed

    def execute(self, request: CommandRequest) -> subprocess.CompletedProcess[str]:
        self.requests.append(request)
        return subprocess.CompletedProcess(list(request.args), 0, "ok", "")

    def close(self) -> None:
        self.closed = True


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _run(tmp_path: Path, runner: FakeRunner, settings: Settings | None = None):
    quality = open_project_quality(
        tmp_path,
        settings or _settings(),
        timeout_seconds=30,
        runner=runner,
    )
    try:
        with quality as handle:
            return handle.run_tests(AgentRole.TESTING, ["-v"])
    finally:
        close = getattr(quality, "close", None)
        if close is not None:
            close()


def _joined(runner: FakeRunner) -> str:
    return " ".join(part for request in runner.requests for part in request.args)


def _heads(runner: FakeRunner) -> list[str]:
    return [request.args[0] for request in runner.requests]


def test_defaults_are_not_an_explicit_quality_selection() -> None:
    assert quality_selection_is_explicit(_settings()) is False
    assert quality_selection_is_explicit(_settings(quality_stack="jvm")) is True
    assert quality_selection_is_explicit(
        _settings(quality_component_path="order-ms")
    ) is True


def test_pom_only_tree_runs_maven_never_pytest(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    runner = FakeRunner()
    _run(tmp_path, runner)

    joined = _joined(runner)
    assert "mvn" in joined
    assert "pytest" not in joined
    assert "python" not in joined


def test_csproj_tree_runs_dotnet_test_never_pytest(tmp_path: Path) -> None:
    (tmp_path / "App.csproj").write_text("<Project/>", encoding="utf-8")
    runner = FakeRunner()
    _run(tmp_path, runner)

    joined = _joined(runner)
    assert _heads(runner)[0] == "dotnet"
    assert "test" in joined
    assert "pytest" not in joined


def test_pyproject_tree_still_runs_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )
    runner = FakeRunner()
    _run(tmp_path, runner)

    joined = _joined(runner)
    assert "pytest" in joined
    assert "mvn" not in joined
    assert "dotnet" not in joined


def test_explicit_quality_stack_override_still_wins(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )
    runner = FakeRunner()
    _run(tmp_path, runner, _settings(quality_stack="jvm"))
    joined = _joined(runner)
    assert "mvn" in joined
    assert "pytest" not in joined


def test_unknown_stack_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="cobol"):
        quality_targets_for(_settings(quality_stack="cobol"), tmp_path)


def test_one_python_component_is_not_a_composite(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
    targets = quality_targets_for(_settings(), tmp_path)
    assert len(targets) == 1
    assert targets[0].stack == "python"
    assert targets[0].path == ""
    runner = FakeRunner()
    quality = open_project_quality(
        tmp_path, _settings(), timeout_seconds=30, runner=runner
    )
    with quality as handle:
        assert not isinstance(handle, CompositeQuality)
        handle.run_tests(AgentRole.TESTING)
    assert "pytest" in _joined(runner)


def test_detected_targets_match_prueba_layout(tmp_path: Path) -> None:
    (tmp_path / "order-ms").mkdir()
    (tmp_path / "payment-ms").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "order-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "payment-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "frontend" / "package.json").write_text("{}\n", encoding="utf-8")
    stacks = [item.stack for item in quality_targets_for(_settings(), tmp_path)]
    assert stacks.count("jvm") == 2
    assert stacks.count("node") == 1
    assert "python" not in stacks


def test_open_quality_fans_out_when_several_components_exist(tmp_path: Path) -> None:
    (tmp_path / "order-ms").mkdir()
    (tmp_path / "payment-ms").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "order-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "payment-ms" / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    recorder = FakeRunner()
    handle = open_project_quality(tmp_path, _settings(), timeout_seconds=30, runner=recorder)
    assert isinstance(handle, CompositeQuality)
    stacks = sorted(backend.profile.name for backend in handle._backends)
    assert stacks == ["jvm", "jvm", "node"]
    handle.run_tests(AgentRole.TESTING, ["-v"])
    handle.close()
    names = _heads(recorder)
    assert names.count("mvn") == 2
    assert "python" not in names
    assert all("-v" not in req.args for req in recorder.requests)


@pytest.mark.parametrize("stack", ["jvm", "dotnet"])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_profile_attaches_fresh_report_cases_and_keeps_cached_result(tmp_path, stack, exit_code):
    from engineering_team.mcp.quality import QualityMCP
    from engineering_team.stacks import profile_for

    class ReportingRunner(FakeRunner):
        def execute(self, request):
            result = super().execute(request)
            if "test" in request.args:
                if stack == "jvm":
                    path = tmp_path / "target/surefire-reports/TEST-Example.xml"
                    report = '<testsuite><testcase classname="Example" name="boundary"/></testsuite>'
                else:
                    assert list(request.args)[-2:] == ["--logger", "trx"]
                    path = tmp_path / "TestResults/run/results.trx"
                    report = ('<TestRun><Results><UnitTestResult testId="1" '
                              'testName="boundary" outcome="Passed"/></Results></TestRun>')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(report)
                result.returncode = exit_code
            return result

    runner = ReportingRunner()
    quality = QualityMCP(tmp_path, runner=runner, profile=profile_for(stack))
    result = quality.run_tests(AgentRole.TESTING)
    assert result.test_cases is not None
    assert len(result.test_cases) == (1 if exit_code == 0 else 0)
    if exit_code == 0:
        assert "boundary" in result.test_cases[0].identifier
    assert quality.get_test_results(AgentRole.TESTING).test_cases == result.test_cases
