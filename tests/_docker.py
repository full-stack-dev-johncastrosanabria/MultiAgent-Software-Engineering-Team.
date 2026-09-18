"""Shared, once-per-process probe for a usable Docker daemon.

A plain module rather than a ``conftest.py`` on purpose: the four test files
that genuinely need a live daemon import ``needs_docker`` explicitly, the same
way ``tests/mcp/test_service_stack.py`` and ``tests/mcp/test_container.py``
already declare their own local markers, so the dependency is visible at the
top of each file instead of arriving through conftest re-export magic.
"""

import shutil
import subprocess

import pytest


def _docker_daemon_reachable() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


# Evaluated once, at import time -- not per test, per fixture invocation or per
# file. The cost of the probe (at most the 5 s timeout above, in practice
# near-instant: an absent socket fails immediately rather than hanging) is paid
# exactly once per pytest process, exactly like test_service_stack.py's own
# module-level marker.
DOCKER_AVAILABLE = _docker_daemon_reachable()

needs_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="needs a live Docker daemon (ContainerRunner.require_available)",
)
