"""A component's command directory must not hide its sibling projects."""

import time
from types import SimpleNamespace

import pytest

from engineering_team.apply_run import open_project_quality
from engineering_team.config import Settings
from engineering_team.mcp.command import CommandRequest
from engineering_team.mcp.quality import QualityMCP, build_runner

PINNED = "python@sha256:" + "0" * 64


def settings(**overrides):
    return Settings(_env_file=None, quality_container_image=PINNED, **overrides)


def test_components_share_repository_visibility_and_keep_separate_environments(tmp_path):
    components = [tmp_path / "app", tmp_path / "shared"]
    for component in components:
        component.mkdir()
    backends = [QualityMCP(root, workspace_root=tmp_path, settings=settings())
                for root in components]
    assert len({backend._runner._volume for backend in backends}) == 2
    for backend, component in zip(backends, components):
        assert backend.root == component
        command = backend._runner._container_command("probe", CommandRequest(
            args=("cat", "../shared/api.txt"), cwd=backend.root,
            deadline=time.monotonic() + 30,
        ))
        assert f"type=bind,source={tmp_path},target=/aset/project-root" in command
        assert command[command.index("--workdir") + 1] == f"/aset/project-root/{component.name}"


def test_component_still_selects_its_own_interpreter(tmp_path):
    component = tmp_path / "app"
    component.mkdir()
    seen = []
    runner = build_runner(component, Settings(_env_file=None), workspace_root=tmp_path,
                          interpreter=lambda root: seen.append(root) or (3, 12))
    assert seen == [component]
    assert runner.workspace == tmp_path


@pytest.mark.parametrize("escape", ["absolute", "parent", "symlink"])
def test_quality_rejects_components_outside_repository_before_runner_creation(tmp_path, monkeypatch, escape):
    repository = tmp_path / "repo"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    component = outside if escape == "absolute" else repository / ".." / "outside"
    if escape == "symlink":
        component = repository / "linked"
        component.symlink_to(outside, target_is_directory=True)
    def forbidden(*args, **kwargs):
        pytest.fail("runner constructed for an escaped component")
    monkeypatch.setattr("engineering_team.mcp.quality.build_runner", forbidden)
    with pytest.raises(ValueError, match="outside the mounted workspace"):
        QualityMCP(component, workspace_root=repository, settings=settings())


def test_build_runner_also_rejects_an_external_component(tmp_path):
    with pytest.raises(ValueError, match="outside the mounted workspace"):
        build_runner(tmp_path.parent, settings(), workspace_root=tmp_path)


def test_apply_components_keep_repository_mount_with_shared_infrastructure(tmp_path, monkeypatch):
    import engineering_team.apply_run as module
    for name in ("app", "shared"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "pom.xml").write_text("<project/>")
    services = SimpleNamespace(
        up=lambda deadline: None, down=lambda: None, network=None, networks=(),
        environment_for_component=lambda stack, root: (),
    )
    monkeypatch.setattr("engineering_team.services.ServiceStack", lambda *args, **kwargs: services)
    monkeypatch.setattr(module, "sweep", lambda run_id: None)
    monkeypatch.setattr(module, "detect_prerequisite", lambda *args: None)
    with open_project_quality(tmp_path, settings(), timeout_seconds=30) as quality:
        assert {backend.root for backend in quality._backends} == {tmp_path / "app", tmp_path / "shared"}
        assert all(backend._runner.workspace == tmp_path for backend in quality._backends)


def test_apply_rejects_escaped_component_before_infrastructure(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("infrastructure constructed for an escaped component")
    monkeypatch.setattr("engineering_team.services.ServiceStack", forbidden)
    with pytest.raises(ValueError, match="outside the mounted workspace"):
        open_project_quality(tmp_path, settings(quality_stack="jvm", quality_component_path="../outside"), timeout_seconds=30)


def test_quality_server_preserves_repository_mount(tmp_path, monkeypatch):
    import engineering_team.mcp.server as module
    component = tmp_path / "app"
    component.mkdir()
    captured = []
    real = module.QualityMCP
    def capture(*args, **kwargs):
        backend = real(*args, **kwargs)
        captured.append(backend)
        return backend
    monkeypatch.setattr(module, "QualityMCP", capture)
    module.build_quality_server(component, workspace_root=tmp_path, settings=settings())
    assert captured[0].root == component
    assert captured[0]._runner.workspace == tmp_path
