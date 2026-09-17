import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engineering_team.mcp.command import CommandRequest
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.workspace_runner import (
    NativeWorkspaceRunner,
    WorkspaceSyncError,
    _apply_host_delta,
    _archive,
    _Entry,
    _read_archive,
    _snapshot,
)


def test_snapshot_round_trip_preserves_binary_modes_links_and_empty_directories(tmp_path):
    (tmp_path / "empty").mkdir()
    (tmp_path / "data").write_bytes(b"\x00\xffbinary")
    (tmp_path / "data").chmod(0o751)
    (tmp_path / "link").symlink_to("data")
    snapshot = _snapshot(tmp_path)
    assert _read_archive(_archive(snapshot)) == snapshot


def test_dependency_trees_remain_private_to_volume(tmp_path):
    (tmp_path / "packages/a/node_modules/pkg").mkdir(parents=True)
    (tmp_path / "packages/a/node_modules/pkg/index.js").write_text("large dependency")
    (tmp_path / "packages/a/source.js").write_text("source")
    assert "packages/a/source.js" in _snapshot(tmp_path)
    assert not any("node_modules" in Path(path).parts for path in _snapshot(tmp_path))


def test_repository_metadata_never_crosses_the_volume_boundary(tmp_path):
    (tmp_path / ".git/hooks").mkdir(parents=True)
    (tmp_path / ".git/config").write_text("[core]\n")
    (tmp_path / "source.js").write_text("source")
    before = _snapshot(tmp_path)
    assert set(before) == {"source.js"}
    tampered = _archive({
        ".git": _Entry("dir", 0o755),
        ".git/hooks": _Entry("dir", 0o755),
        ".git/hooks/pre-push": _Entry("file", 0o755, b"#!/bin/sh\ntouch /tmp/owned\n"),
        "source.js": _Entry("file", 0o644, b"source"),
    })
    after = _read_archive(tampered)
    assert set(after) == {"source.js"}
    _apply_host_delta(tmp_path, before, after)
    assert not (tmp_path / ".git/hooks/pre-push").exists()
    assert (tmp_path / ".git/config").read_text() == "[core]\n"


def test_native_command_still_sees_repository_metadata_read_only(tmp_path):
    (tmp_path / ".git").mkdir()
    args = _runner(tmp_path)._container_command("command", CommandRequest(
        args=("git", "status"), cwd=tmp_path, deadline=time.monotonic() + 60))
    assert f"type=bind,source={tmp_path / '.git'},target=/aset/project-root/.git,readonly" in args


@pytest.mark.parametrize("target", ["/etc/passwd", "../outside", "a/../../outside"])
def test_snapshot_refuses_external_symlinks(tmp_path, target):
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(WorkspaceSyncError):
        _snapshot(tmp_path)


def test_delta_exports_generated_files_and_deleted_and_changed_sources(tmp_path):
    (tmp_path / "source.js").write_text("before")
    (tmp_path / "deleted.js").write_text("delete")
    before = _snapshot(tmp_path)
    after = {
        "source.js": _Entry("file", 0o644, b"after"),
        "reports": _Entry("dir", 0o755),
        "reports/result.json": _Entry("file", 0o644, b'{"passed": 3}'),
    }
    _apply_host_delta(tmp_path, before, after)
    assert _snapshot(tmp_path) == after


def test_concurrent_host_edit_is_not_overwritten(tmp_path):
    path = tmp_path / "source.js"
    path.write_text("before")
    before = _snapshot(tmp_path)
    path.write_text("user edit")
    with pytest.raises(WorkspaceSyncError, match="conflict"):
        _apply_host_delta(tmp_path, before, {"source.js": _Entry("file", 0o644, b"tool edit")})
    assert path.read_text() == "user edit"


def test_unrelated_concurrent_edit_survives_export(tmp_path):
    (tmp_path / "a").write_text("a")
    (tmp_path / "b").write_text("b")
    before = _snapshot(tmp_path)
    (tmp_path / "b").write_text("user edit")
    after = before | {"a": _Entry("file", 0o644, b"tool edit")}
    _apply_host_delta(tmp_path, before, after)
    assert (tmp_path / "a").read_text() == "tool edit"
    assert (tmp_path / "b").read_text() == "user edit"


def test_concurrent_parent_symlink_is_not_followed(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder/source").write_text("before")
    (tmp_path / "other").mkdir()
    before = _snapshot(tmp_path)
    (tmp_path / "folder/source").unlink()
    (tmp_path / "folder").rmdir()
    (tmp_path / "folder").symlink_to("other", target_is_directory=True)
    after = before | {"folder/source": _Entry("file", 0o644, b"tool edit")}
    with pytest.raises(WorkspaceSyncError):
        _apply_host_delta(tmp_path, before, after)
    assert not (tmp_path / "other/source").exists()


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../../escape"])
def test_archive_refuses_traversal(path):
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(path)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(WorkspaceSyncError):
        _read_archive(buffer.getvalue())


def test_archive_refuses_member_below_symlink():
    with pytest.raises(WorkspaceSyncError):
        _read_archive(_archive({
            "link": _Entry("link", 0o777, target="other"),
            "link/child": _Entry("file", 0o644, b"x"),
        }))


def test_export_breaks_host_hardlinks_instead_of_modifying_external_file(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("must survive")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "file").hardlink_to(outside)
    before = _snapshot(workspace)
    _apply_host_delta(workspace, before, {"file": _Entry("file", 0o644, b"changed")})
    assert outside.read_text() == "must survive"


def test_export_readonly_generated_directory(tmp_path):
    after = {"reports": _Entry("dir", 0o500),
             "reports/file": _Entry("file", 0o400, b"evidence")}
    try:
        _apply_host_delta(tmp_path, {}, after)
        assert _snapshot(tmp_path) == after
    finally:
        (tmp_path / "reports").chmod(0o700)


def _runner(tmp_path):
    return NativeWorkspaceRunner(tmp_path, image="node@sha256:" + "0" * 64,
                                 run_id="workspace-test", project="example")


@pytest.mark.parametrize("stack, native", [
    ("node", True), ("python", False), ("jvm", False), ("dotnet", False),
])
def test_only_node_components_leave_the_bind_mount(tmp_path, stack, native):
    from engineering_team.config import Settings
    from engineering_team.mcp.quality import build_runner

    component = tmp_path / "client"
    component.mkdir()
    settings = Settings(_env_file=None, quality_runner="container", quality_stack=stack)
    runner = build_runner(component, settings, workspace_root=tmp_path,
                          interpreter=lambda _root: (3, 12))
    assert isinstance(runner, NativeWorkspaceRunner) is native
    assert runner.workspace == tmp_path.resolve()


def test_command_mounts_entire_native_workspace_and_translates_component(tmp_path):
    (tmp_path / "client").mkdir()
    runner = _runner(tmp_path)
    request = CommandRequest(args=("npm", "test"), cwd=tmp_path / "client",
                             deadline=time.monotonic() + 60)
    args = runner._container_command("command", request)
    assert not any("type=bind" in arg for arg in args)
    assert f"type=volume,source={runner._workspace_volume},target=/aset/project-root" in args
    assert args[args.index("--workdir") + 1] == "/aset/project-root/client"


def test_execute_pushes_host_deletions_and_edits_and_exports_even_failed_command(tmp_path, monkeypatch):
    (tmp_path / "source").write_text("before")
    (tmp_path / "deleted").write_text("remove")
    runner = _runner(tmp_path)
    runner._published = _snapshot(tmp_path)
    (tmp_path / "deleted").unlink()
    (tmp_path / "source").write_text("host edit")
    pushed = []
    monkeypatch.setattr(runner, "_ensure_workspace", lambda deadline: None)
    monkeypatch.setattr(runner, "_push", lambda snapshot, deadline: pushed.append(snapshot))
    remote = _snapshot(tmp_path) | {"result.json": _Entry("file", 0o644, b"failure evidence")}
    monkeypatch.setattr(runner, "_pull", lambda deadline: remote)
    monkeypatch.setattr(ContainerRunner, "execute", lambda self, request: subprocess.CompletedProcess([], 1, "", "failed"))
    result = runner.execute(CommandRequest(args=("npm", "test"), cwd=tmp_path,
                                           deadline=time.monotonic() + 60))
    assert result.returncode == 1
    assert "deleted" not in pushed[0]
    assert pushed[0]["source"].data == b"host edit"
    assert (tmp_path / "result.json").read_text() == "failure evidence"


def test_failed_pull_poisoning_prevents_reuse_of_divergent_workspace(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    monkeypatch.setattr(runner, "_ensure_workspace", lambda deadline: None)
    monkeypatch.setattr(runner, "_push", lambda snapshot, deadline: None)
    monkeypatch.setattr(ContainerRunner, "execute", lambda self, request: subprocess.CompletedProcess([], 0, "", ""))

    def fail(deadline):
        raise WorkspaceSyncError("bad archive")

    monkeypatch.setattr(runner, "_pull", fail)
    request = CommandRequest(args=("true",), cwd=tmp_path, deadline=time.monotonic() + 60)
    with pytest.raises(WorkspaceSyncError, match="bad archive"):
        runner.execute(request)
    with pytest.raises(WorkspaceSyncError, match="synchronization failed"):
        runner.execute(request)


def test_close_only_removes_owned_volumes(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    runner._workspace_created = True
    runner._volume_created = True
    calls = []
    monkeypatch.setattr(runner, "_quiet", lambda args, **kwargs: calls.append(args))
    runner.close()
    removals = [args[-1] for args in calls if args[1:3] == ["volume", "rm"]]
    assert set(removals) == {runner._workspace_volume, runner._volume}
    assert all("prune" not in args for args in calls)


def test_transfer_preserves_nonzero_exit_even_with_valid_archive_output():
    with pytest.raises(WorkspaceSyncError, match="container failed"):
        NativeWorkspaceRunner._transfer_output([sys.executable, "-c", "import sys; print('output'); sys.exit(2)"], None, 5)


def test_transfer_refuses_truncated_output_instead_of_parsing_it(monkeypatch):
    import engineering_team.mcp.workspace_runner as module

    monkeypatch.setattr(module, "_TRANSFER_LIMIT", 10)
    with pytest.raises(WorkspaceSyncError, match="size limit"):
        NativeWorkspaceRunner._transfer_output([sys.executable, "-c", "print('x' * 100)"], None, 5)


@pytest.mark.parametrize("kind", ["hardlink", "fifo", "duplicate"])
def test_archive_refuses_special_files_hardlinks_and_duplicates(kind):
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("source")
        if kind == "hardlink":
            info.type = tarfile.LNKTYPE
            info.linkname = "../outside"
        elif kind == "fifo":
            info.type = tarfile.FIFOTYPE
        archive.addfile(info)
        if kind == "duplicate":
            archive.addfile(info)
    with pytest.raises(WorkspaceSyncError):
        _read_archive(buffer.getvalue())


def test_close_during_command_does_not_start_an_export_container(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    monkeypatch.setattr(runner, "_ensure_workspace", lambda deadline: None)
    monkeypatch.setattr(runner, "_push", lambda snapshot, deadline: None)
    exports = []
    monkeypatch.setattr(runner, "_pull", lambda deadline: exports.append(deadline))

    def stop(self, request):
        self._closing_event.set()
        return subprocess.CompletedProcess([], 137, "", "")

    monkeypatch.setattr(ContainerRunner, "execute", stop)
    result = runner.execute(CommandRequest(args=("npm", "test"), cwd=tmp_path,
                                          deadline=time.monotonic() + 60))
    assert result.returncode == 137
    assert not exports


@pytest.mark.skipif(not os.environ.get("ASET_NATIVE_WORKSPACE_TEST_IMAGE"),
                    reason="set ASET_NATIVE_WORKSPACE_TEST_IMAGE to an available pinned Node image")
def test_real_npm_workspace_sees_siblings_and_incremental_host_changes(tmp_path):
    import uuid

    run_id = "native-workspace-test-" + uuid.uuid4().hex[:12]
    app = tmp_path / "packages/app"
    shared = tmp_path / "packages/shared"
    app.mkdir(parents=True)
    shared.mkdir()
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test-workspace", "private": True, "workspaces": ["packages/*"]}))
    (app / "package.json").write_text(json.dumps({
        "name": "@probe/app", "version": "1.0.0", "scripts": {"build": "node build.js"},
        "dependencies": {"@probe/shared": "1.0.0"}}))
    (shared / "package.json").write_text(json.dumps({
        "name": "@probe/shared", "version": "1.0.0", "main": "index.js"}))
    (shared / "index.js").write_text("module.exports = 'before';")
    (app / "build.js").write_text(
        "const fs = require('fs'); fs.mkdirSync('dist', {recursive: true}); "
        "fs.writeFileSync('dist/result.txt', require('@probe/shared'));")
    runner = NativeWorkspaceRunner(tmp_path, image=os.environ["ASET_NATIVE_WORKSPACE_TEST_IMAGE"],
                                   run_id=run_id, project="native-workspace-test")

    def execute(*args):
        result = runner.execute(CommandRequest(args=args, cwd=app,
            deadline=time.monotonic() + 120,
            env=(("npm_config_cache", "/aset/environment/npm"),)))
        assert result.returncode == 0, (result.stdout + result.stderr)[-1000:]

    try:
        execute("npm", "install", "--no-audit", "--no-fund", "--ignore-scripts")
        execute("npm", "run", "build")
        assert (app / "dist/result.txt").read_text() == "before"
        (shared / "index.js").write_text("module.exports = 'host edit';")
        execute("npm", "run", "build")
        assert (app / "dist/result.txt").read_text() == "host edit"
        assert not (tmp_path / "node_modules").exists()
        assert not (app / "node_modules").exists()
        assert (tmp_path / "package-lock.json").is_file()
    finally:
        runner.close()
    for command in (["docker", "ps", "-aq"], ["docker", "volume", "ls", "-q"]):
        result = subprocess.run([*command, "--filter", f"label=aset.run={run_id}"],
                                capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode == 0
        assert not result.stdout.strip()
