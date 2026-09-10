"""Opt-in Docker checks for the ADR 14 boundary, independent of LLM providers."""

import json
import os
import subprocess
import time

import pytest

from engineering_team.mcp.run_daemon import RunDaemon, RunDaemonStartupError

pytestmark = pytest.mark.skipif(
    os.environ.get("ASET_RUN_DAEMON_LIVE") != "1", reason="requires live Docker daemon images",
)
IMAGE = (
    "docker:dind-rootless@sha256:"
    "e17fa54c2ffd511d8407c746eec77f7814e6f74fe20caf822dad1870599984c0"
)


def docker(*args, check=True):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=60, check=check,
    )


def client(owner, *args, check=True):
    return docker(
        "run", "--rm", "--network", owner.network,
        "--env", "DOCKER_HOST=tcp://dind:2375", "docker:cli", *args, check=check,
    )


def test_real_daemons_isolate_runs_close_egress_and_clean_up():
    first = RunDaemon(image=IMAGE, images=("docker:cli",))
    second = RunDaemon(image=IMAGE, images=())
    try:
        first.up(time.monotonic() + 180)
        second.up(time.monotonic() + 180)
        inspected = json.loads(docker("inspect", first.name).stdout)[0]
        host = inspected["HostConfig"]
        assert host["Privileged"] is False
        assert not host["CapAdd"]
        assert not host["Binds"]
        assert not any(mount["Type"] == "bind" for mount in inspected["Mounts"])
        assert [item["PathOnHost"] for item in host["Devices"]] == ["/dev/net/tun"]
        assert json.loads(docker("network", "inspect", first.network).stdout)[0]["Internal"]
        assert "rootless" in client(first, "docker", "info", "--format",
                                    "{{json .SecurityOptions}}").stdout
        client(first, "docker", "create", "--name", "owned-by-first", "docker:cli", "true")
        assert "owned-by-first" in client(first, "docker", "ps", "-a", "--format",
                                          "{{.Names}}").stdout
        assert client(second, "docker", "ps", "-a", "--format", "{{.Names}}").stdout == ""
        assert client(first, "docker", "run", "--rm", "docker:cli", "echo",
                      "nested-runtime-works").stdout.strip() == "nested-runtime-works"
        assert client(first, "sh", "-c", "test ! -S /var/run/docker.sock").returncode == 0
        assert client(first, "wget", "-T", "3", "-q", "-O", "/dev/null",
                      "http://1.1.1.1", check=False).returncode != 0
        assert client(first, "docker", "run", "--rm", "docker:cli", "wget", "-T", "3",
                      "-q", "-O", "/dev/null", "http://1.1.1.1", check=False).returncode != 0
    finally:
        first.close()
        second.close()
    for owner in (first, second):
        assert docker("inspect", owner.name, check=False).returncode != 0
        assert docker("network", "inspect", owner.network, check=False).returncode != 0


def test_real_partial_startup_removes_container_and_network():
    owner = RunDaemon(image=IMAGE, images=("aset-adr14-nonexistent-suite-image:never",))
    with pytest.raises(RunDaemonStartupError, match="host cache"):
        owner.up(time.monotonic() + 90)
    assert docker("inspect", owner.name, check=False).returncode != 0
    assert docker("network", "inspect", owner.network, check=False).returncode != 0
