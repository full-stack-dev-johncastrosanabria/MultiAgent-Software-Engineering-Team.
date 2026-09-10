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
    assert args[args.index("--runner") + 1] == "container"


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


# -- Finding 19: the component's stack is exactly as explicit as its image -----


def test_the_configured_stack_travels_as_an_argument(tmp_path) -> None:
    settings = Settings(quality_stack="jvm", quality_component_path="order-ms")
    args = MCPQualityClient(tmp_path, settings=settings)._parameters().args

    assert args[args.index("--stack") + 1] == "jvm"
    assert args[args.index("--component-root") + 1] == "order-ms"


def test_the_default_stack_and_component_root_carry_the_default(tmp_path) -> None:
    args = MCPQualityClient(tmp_path)._parameters().args
    assert args[args.index("--stack") + 1] == "python"
    assert args[args.index("--component-root") + 1] == ""


def test_the_server_carries_the_stack_argument_into_settings() -> None:
    from engineering_team.mcp.server import settings_from_arguments

    settings = settings_from_arguments(runner="container", image=PINNED, stack="jvm")
    assert settings.quality_stack == "jvm"


def test_main_resolves_the_quality_root_beneath_the_component_path(
    tmp_path, monkeypatch
) -> None:
    """`--root` names the repository; a Maven module of it is not the repository."""
    import engineering_team.mcp.server as server_module

    class _StubServer:
        def run(self, transport: str) -> None:
            return None

    component = tmp_path / "order-ms"
    component.mkdir()
    captured: dict[str, object] = {}

    def spy(root, timeout, *, settings):
        captured["root"] = root
        captured["settings"] = settings
        return _StubServer()

    monkeypatch.setattr(server_module, "build_quality_server", spy)
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog", "--kind", "quality", "--root", str(tmp_path),
            "--stack", "jvm", "--component-root", "order-ms",
        ],
    )
    server_module.main()

    assert captured["root"] == component
    assert captured["settings"].quality_stack == "jvm"
