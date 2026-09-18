from types import SimpleNamespace

import pytest

from engineering_team.apply_run import open_project_quality
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult


@pytest.mark.parametrize("initial_components", [1, 2])
def test_new_test_project_is_executed_and_closed_without_restarting_services(
    tmp_path, monkeypatch, initial_components,
):
    import engineering_team.apply_run as module

    for i in range(initial_components):
        root = tmp_path / f"app{i}"
        root.mkdir()
        (root / "App.csproj").write_text("<Project/>")
    calls, closed, services_calls = [], [], []

    class Backend:
        def __init__(self, root, **kwargs):
            self.root = root
            self.workspace_root = kwargs["workspace_root"]
            self.profile = kwargs["profile"]
            self._runner = SimpleNamespace()

        def run_tests(self, role, paths=None):
            calls.append(self.root.name)
            return ToolResult(
                tool_name="run_tests", allowed_role=role, status=ToolStatus.SUCCESS,
                input_summary=self.root.name, output_summary="1 passed", duration_ms=1,
            )

        def close(self):
            closed.append(self.root.name)

    services = SimpleNamespace(
        up=lambda deadline: services_calls.append("up"),
        down=lambda: services_calls.append("down"), network=None, networks=(),
        environment_for_component=lambda stack, root: (),
    )
    monkeypatch.setattr("engineering_team.services.ServiceStack", lambda *a, **kw: services)
    monkeypatch.setattr("engineering_team.mcp.quality.QualityMCP", Backend)
    # A `SweepReport`, not `None`: the caller reads `["error_code"]` off this
    # return value (A-13/B-11 -- a hung runtime must not be mistaken for a
    # sweep that ran and found nothing), so the stub has to answer the same
    # shape the real function does.
    monkeypatch.setattr(module, "sweep", lambda *a: {
        "containers": [], "networks": [], "volumes": [], "images": [], "error_code": None,
    })
    monkeypatch.setattr(module, "detect_prerequisite", lambda *a: None)
    settings = Settings(_env_file=None, quality_run_daemon_image="")
    with open_project_quality(tmp_path, settings, timeout_seconds=30) as quality:
        new = tmp_path / "tests" / "New.Tests"
        new.mkdir(parents=True)
        (new / "New.Tests.csproj").write_text("<Project/>")
        quality.run_tests(AgentRole.TESTING)
        assert "New.Tests" in calls
        assert len(calls) == initial_components + 1
        calls.clear()
        quality.run_tests(AgentRole.TESTING)
        assert len(calls) == initial_components + 1
    assert sorted(closed) == sorted([f"app{i}" for i in range(initial_components)] + ["New.Tests"])
    assert services_calls == ["up", "down"]
