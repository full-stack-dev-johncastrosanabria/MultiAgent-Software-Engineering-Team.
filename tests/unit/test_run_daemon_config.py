"""The daemon is an explicit operator choice, never a silent fallback."""

import pytest
from pydantic import ValidationError

from engineering_team.config import Settings

IMAGE = "docker:dind-rootless@sha256:" + "a" * 64


def test_run_daemon_configuration_is_explicit():
    settings = Settings(_env_file=None, quality_runner="container",
                        quality_run_daemon_image=IMAGE,
                        quality_run_daemon_images=("postgres:17-alpine",))
    assert settings.quality_run_daemon_image == IMAGE
    assert settings.quality_run_daemon_images == ("postgres:17-alpine",)


@pytest.mark.parametrize("overrides", [
    {"quality_runner": "process", "quality_run_daemon_image": IMAGE},
    {"quality_runner": "container", "quality_run_daemon_image": "docker:dind-rootless"},
    {"quality_runner": "container", "quality_run_daemon_images": ("postgres:17-alpine",)},
    {"quality_runner": "container", "quality_run_daemon_image": IMAGE,
     "quality_run_daemon_images": ("--help",)},
])
def test_invalid_run_daemon_configuration_is_refused(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_daemon_settings_survive_mcp_arguments(tmp_path):
    from engineering_team.mcp.client import MCPQualityClient
    from engineering_team.mcp.server import settings_from_arguments

    settings = Settings(_env_file=None, quality_runner="container",
                        quality_run_daemon_image=IMAGE,
                        quality_run_daemon_images=("postgres:17-alpine", "apache/kafka:4.3.1"))
    client = MCPQualityClient(tmp_path, settings=settings)
    # The transport owns argv construction; the facade delegates to it.
    transport = getattr(client, "_client", client)
    args = transport._parameters().args
    assert args[args.index("--run-daemon-image") + 1] == IMAGE
    assert args.count("--run-daemon-suite-image") == 2
    restored = settings_from_arguments(runner="container", image="", run_daemon_image=IMAGE,
                                       run_daemon_images=settings.quality_run_daemon_images)
    assert restored.quality_run_daemon_images == settings.quality_run_daemon_images
