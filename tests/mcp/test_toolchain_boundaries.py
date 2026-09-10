"""Whether the boundary could host the suite at all, asked before the run.

The multistack series could not answer it: a Testcontainers suite spent three
runs failing on an image pull that was never going to succeed. The JDK half of
this file went with the process sandbox (ADR 15) -- a container carries its own
JDK, so there is no host toolchain left to pass through or to refuse.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.quality import QualityMCP
from engineering_team.stacks import profile_for


def _component(marker: str, manifest: str = "pom.xml") -> Path:
    root = Path(tempfile.mkdtemp())
    (root / manifest).write_text(marker, encoding="utf-8")
    return root


def test_a_testcontainers_suite_is_refused_before_the_run_not_during() -> None:
    """Three trials read the same pull failure as a flake.

    `ContainerFetchException` after minutes of work names neither the cause nor
    the remedy. The refusal has to arrive before the work, and say where the
    suite does run. Since ADR 14 that place is a daemon of the run's own, not
    the process sandbox the first version of this refusal pointed at.
    """
    root = _component("<project>org.testcontainers</project>")
    quality = QualityMCP(
        root,
        runner=ContainerRunner(root, image=profile_for("jvm").image),
        profile=profile_for("jvm"),
        component="order-ms",
    )

    result = quality.run_tests(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert result.duration_ms == 0
    assert "quality_run_daemon_image" in (result.error or "")
    assert "quality_run_daemon_images" in (result.error or "")
    assert "ADR 14" in (result.error or "")


def test_a_component_that_starts_no_containers_still_runs_in_one() -> None:
    root = _component("<project/>")
    quality = QualityMCP(
        root,
        runner=ContainerRunner(root, image=profile_for("jvm").image),
        profile=profile_for("jvm"),
    )

    assert quality._container_api_refusal() is None
