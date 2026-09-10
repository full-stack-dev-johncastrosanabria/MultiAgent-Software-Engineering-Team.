"""D2 fp-quality-env-nonpython: a jvm or node component needs no venv to run.

`prepare_environment` used to be the only thing that created the directory the
gate runs in, so every jvm and node component failed with `quality environment
has not been created` before a tool ran. Four tests pinned the fix on the
process sandbox, where the directory was created lazily and could still be
absent.

The container cannot reproduce that failure: its environment is a volume
mounted at a fixed path, so `ContainerRunner.environment` is set the moment the
runner exists, before any profile is consulted. What is left to protect is that
this stays true -- a runner whose environment is None again would bring the
whole class of failures back for every non-Python stack at once.
"""

from __future__ import annotations

from pathlib import Path

from engineering_team.mcp.container import ENVIRONMENT_MOUNT, ContainerRunner
from engineering_team.mcp.quality import QualityMCP
from engineering_team.stacks import profile_for

PINNED = "python@sha256:" + "0" * 64


def test_the_environment_exists_before_any_profile_is_consulted(
    tmp_path: Path,
) -> None:
    """No provisioning has run, and no command has been built."""
    runner = ContainerRunner(tmp_path, image=PINNED)

    assert runner.environment == Path(ENVIRONMENT_MOUNT)


def test_no_stack_starts_without_a_directory_to_run_in(tmp_path: Path) -> None:
    """The scratch path is non-empty for the profiles that name no interpreter.

    Maven and npm name their own binary, which is what left them without one.
    """
    for stack in ("jvm", "node", "dotnet", "go", "python"):
        runner = ContainerRunner(tmp_path, image=PINNED)
        quality = QualityMCP(tmp_path, runner=runner, profile=profile_for(stack))
        try:
            assert quality._sandbox_directory() == str(ENVIRONMENT_MOUNT)
        finally:
            quality.close()
