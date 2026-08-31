"""Configuration has to reach the process that acts on it (finding 12).

The MCP SDK launches a server with a scrubbed environment — HOME, LOGNAME, PATH,
SHELL and USER, and nothing else. So `QUALITY_RUNNER=container` was accepted by
the parent, ignored by the child, and a run that looked configured for containers
quietly used the process sandbox on the operator's Python 3.14.

Worse than not working: it works through `.env`, because Settings reads that file
by path inside the child. An operator who tests one way and deploys the other
gets a different system.
"""

from __future__ import annotations

import pytest

from engineering_team.config import Settings
from engineering_team.mcp.client import MCPQualityClient

PINNED = "python@sha256:" + "0" * 64


def test_the_sdk_passes_almost_nothing_to_the_server() -> None:
    """The fact the fix exists for; asserted so it cannot quietly change."""
    from mcp.client.stdio import get_default_environment

    assert "QUALITY_RUNNER" not in get_default_environment()


def test_the_runner_choice_travels_as_an_argument(tmp_path) -> None:
    """Explicit beats inherited: the child is told, not left to guess."""
    settings = Settings(quality_runner="container", quality_container_image=PINNED)
    client = MCPQualityClient(tmp_path, settings=settings)
    args = client._parameters().args

    assert "--runner" in args
    assert args[args.index("--runner") + 1] == "container"
    assert args[args.index("--image") + 1] == PINNED


def test_the_default_carries_the_default(tmp_path) -> None:
    args = MCPQualityClient(tmp_path)._parameters().args
    assert args[args.index("--runner") + 1] == "process"


def test_quality_timeout_travels_to_the_server(tmp_path) -> None:
    client = MCPQualityClient(tmp_path, timeout_seconds=420)
    args = client._parameters().args

    assert args[args.index("--timeout") + 1] == "420"


def test_the_server_builds_what_the_argument_asked_for(tmp_path) -> None:
    from engineering_team.mcp.server import settings_from_arguments

    settings = settings_from_arguments(runner="container", image=PINNED)
    assert settings.quality_runner == "container"
    assert settings.quality_container_image == PINNED


def test_an_unknown_runner_reaches_the_server_and_is_refused(tmp_path) -> None:
    """The refusal belongs where the runner is built, not in the argument parser."""
    from engineering_team.mcp.quality import build_runner
    from engineering_team.mcp.server import settings_from_arguments

    settings = settings_from_arguments(runner="carrier-pigeon", image="")
    with pytest.raises(ValueError, match="unknown quality_runner"):
        build_runner(tmp_path, settings)
