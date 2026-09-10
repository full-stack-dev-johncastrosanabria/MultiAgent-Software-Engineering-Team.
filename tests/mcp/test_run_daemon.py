import subprocess
import time

import pytest

from engineering_team.mcp.run_daemon import RunDaemon, RunDaemonStartupError

IMAGE = "docker:dind-rootless@sha256:" + "a" * 64


def daemon():
    return RunDaemon(image=IMAGE, images=())


def test_image_must_be_pinned():
    with pytest.raises(ValueError, match="digest"):
        RunDaemon(image="docker:dind-rootless", images=())


def test_runs_are_distinct_even_with_same_label():
    first = RunDaemon(image=IMAGE, images=(), run_id="same")
    second = RunDaemon(image=IMAGE, images=(), run_id="same")
    assert first.network != second.network


def test_internal_unprivileged_topology(monkeypatch):
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    monkeypatch.setattr(subprocess, "run", run)
    owner = daemon().up(time.monotonic() + 5)
    start = next(c for c in commands if "run" in c)
    assert "--internal" in commands[0]
    assert "--privileged" not in start
    assert "--cap-add" not in start
    assert "--publish" not in start and "-p" not in start
    assert "--volume" not in start and "-v" not in start
    assert "seccomp=unconfined" in start
    assert "systempaths=unconfined" in start
    assert "/dev/net/tun" in start
    assert "--network-alias" in start and "dind" in start
    assert dict(owner.environment)["DOCKER_HOST"] == "tcp://dind:2375"
    owner.close()
    count = len(commands)
    owner.close()
    assert len(commands) == count
    assert any(c[1:3] == ["rm", "-f"] and "-v" in c for c in commands)
    assert commands[-1][1:3] == ["network", "rm"]


def test_failed_start_cleans_partial_container_and_network(monkeypatch):
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        if "run" in argv:
            return subprocess.CompletedProcess(argv, 1, b"", b"denied")
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RunDaemonStartupError, match="denied"):
        daemon().up(time.monotonic() + 5)
    assert any(c[1:3] == ["rm", "-f"] for c in commands)
    assert commands[-1][1:3] == ["network", "rm"]


def test_missing_cached_image_does_not_pull(monkeypatch):
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        rc = 1 if argv[1:3] == ["image", "inspect"] else 0
        return subprocess.CompletedProcess(argv, rc, b"", b"missing")
    monkeypatch.setattr(subprocess, "run", run)
    owner = RunDaemon(image=IMAGE, images=("postgres:17-alpine",))
    with pytest.raises(RunDaemonStartupError, match="host cache"):
        owner.up(time.monotonic() + 5)
    assert not any("pull" in c for c in commands)


def test_expired_deadline_refuses_start():
    with pytest.raises(RunDaemonStartupError, match="deadline"):
        daemon().up(time.monotonic() - 1)


def test_health_probe_explicitly_addresses_rootless_daemon(monkeypatch):
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    owner = daemon().up(time.monotonic() + 5)
    assert ["docker", "exec", owner.name, "docker",
            "--host=tcp://127.0.0.1:2375", "info"] in commands
    owner.close()
