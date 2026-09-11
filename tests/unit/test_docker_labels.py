"""What ASET writes on the resources it creates, and what the sweep refuses.

ADR 16. The labels are bookkeeping, so most of these read the argv or the
generated compose rather than start anything: what is worth asserting is that
every creation path carries the run, and that no query ever reaches a resource
nobody labelled.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from engineering_team import docker_labels
from engineering_team.docker_labels import (
    CACHE_LIFETIME,
    OWNER_LABEL,
    PROJECT_LABEL,
    RUN_LABEL,
    label_arguments,
    labels,
    project_slug,
    sweep,
)
from engineering_team.mcp.command import CommandRequest
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.run_daemon import RunDaemon
from engineering_team.services import ServiceStack, override_document

PINNED = "python@sha256:" + "0" * 64


def _pairs(argv: list[str]) -> dict[str, str]:
    """The `--label key=value` pairs of a command line, as a mapping."""
    found = {}
    for index, item in enumerate(argv):
        if item == "--label":
            key, _, value = argv[index + 1].partition("=")
            found[key] = value
    return found


def test_every_label_is_present_and_the_project_is_optional() -> None:
    complete = labels("apply-1", "ingresos")
    assert complete == {
        OWNER_LABEL: "aset", RUN_LABEL: "apply-1",
        "aset.lifetime": "run", PROJECT_LABEL: "ingresos",
    }
    assert PROJECT_LABEL not in labels("apply-1")
    assert labels("apply-1", lifetime=CACHE_LIFETIME)["aset.lifetime"] == "cache"


def test_a_lifetime_outside_the_two_the_record_defines_is_refused() -> None:
    with pytest.raises(ValueError):
        labels("apply-1", lifetime="forever")


def test_a_run_without_an_identity_still_carries_the_owner() -> None:
    assert labels("")[OWNER_LABEL] == "aset"
    assert labels("")[RUN_LABEL] == "unknown"


def test_the_slug_is_the_project_a_person_recognises(tmp_path: Path) -> None:
    project = tmp_path / "Ingresos Backend"
    project.mkdir()
    assert project_slug(project) == "ingresos-backend"


def test_the_command_container_says_which_run_created_it(tmp_path: Path) -> None:
    runner = ContainerRunner(tmp_path, image=PINNED, run_id="apply-1", project="ingresos")
    argv = runner._container_command(
        "aset-1", CommandRequest(args=("true",), cwd=tmp_path,
                                 deadline=time.monotonic() + 60)
    )
    assert _pairs(argv) == labels("apply-1", "ingresos")


def test_the_environment_volume_says_which_run_created_it(tmp_path: Path) -> None:
    runner = ContainerRunner(tmp_path, image=PINNED, run_id="apply-1", project="ingresos")
    seen: list[list[str]] = []
    runner._quiet = lambda argv, timeout: seen.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")
    runner._hand_volume_to_the_unprivileged_user = lambda: None
    runner._ensure_volume()
    created, = [argv for argv in seen if "volume" in argv]
    assert _pairs(created) == labels("apply-1", "ingresos")
    assert created[-1] == runner._volume


def test_the_run_daemon_and_its_network_say_which_run_created_them() -> None:
    daemon = RunDaemon(image=PINNED, images=(), run_id="apply-1", project="ingresos")
    assert _pairs(list(daemon.labels)) == labels("apply-1", "ingresos")


def test_the_compose_project_is_named_after_the_project_not_the_run(tmp_path: Path) -> None:
    project = tmp_path / "ingresos"
    project.mkdir()
    stack = ServiceStack(project, "apply-3f2a-4c11")
    assert stack.project == "aset-ingresos"
    assert stack.slug == "ingresos"
    assert stack.run_id == "apply-3f2a-4c11"


def test_the_override_labels_every_service_network_and_volume() -> None:
    document = override_document(
        ("db",), ("default",), "aset-ingresos", ("pgdata",),
        run_id="apply-1", slug="ingresos",
    )
    assert document.count("aset.run: apply-1") == 3
    assert document.count("aset.project: ingresos") == 3
    assert document.count("aset.owner: aset") == 3


def test_a_second_run_on_a_project_another_run_holds_is_refused(tmp_path, monkeypatch):
    from engineering_team.services import ServiceStartupError

    project = tmp_path / "ingresos"
    project.mkdir()
    stack = ServiceStack(project, "apply-second")
    monkeypatch.setattr("engineering_team.services.shutil.which", lambda _name: "/usr/bin/docker")

    def _ps(argv, **kwargs):
        mine = f"label={RUN_LABEL}=apply-second" in argv
        return subprocess.CompletedProcess(argv, 0, "" if mine else "abc123\n", "")

    monkeypatch.setattr("engineering_team.services.subprocess.run", _ps)
    with pytest.raises(ServiceStartupError, match="already held"):
        stack._refuse_a_concurrent_run()


def test_a_project_only_this_run_holds_is_not_refused(tmp_path, monkeypatch):
    project = tmp_path / "ingresos"
    project.mkdir()
    stack = ServiceStack(project, "apply-only")
    monkeypatch.setattr("engineering_team.services.shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        "engineering_team.services.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "abc123\n", ""),
    )
    stack._refuse_a_concurrent_run()


class _Runtime:
    """A docker that answers list queries from a table and records removals."""

    def __init__(self, listings: dict[tuple[str, ...], str]) -> None:
        self.listings = listings
        self.removed: list[list[str]] = []
        self.listed: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        key = tuple(argv[1:])
        if any(item in argv for item in ("ps", "ls", "images")):
            self.listed.append(argv)
        if key in self.listings:
            return subprocess.CompletedProcess(argv, 0, self.listings[key], "")
        if any(item in argv for item in ("rm", "prune")):
            self.removed.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def _sweep_with(monkeypatch, listings) -> _Runtime:
    runtime = _Runtime(listings)
    monkeypatch.setattr(docker_labels.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(docker_labels.subprocess, "run", runtime)
    return runtime


OWNED = ("--filter", "label=aset.owner=aset")


def test_the_sweep_leaves_the_current_run_alone(monkeypatch) -> None:
    runtime = _sweep_with(monkeypatch, {
        ("ps", "-a", "--quiet", *OWNED): "dead\nalive\n",
        ("ps", "-a", "--quiet", *OWNED, "--filter", "label=aset.run=now"): "alive\n",
    })
    report = sweep("now")
    assert report["containers"] == ["dead"]
    assert ["docker", "rm", "--force", "alive"] not in runtime.removed


def test_the_sweep_never_asks_for_a_resource_without_the_owner_label(monkeypatch) -> None:
    """An unlabelled resource is not a candidate, so nothing is removed."""
    runtime = _sweep_with(monkeypatch, {})
    sweep("now")
    assert runtime.removed == []
    for argv in runtime.listed:
        assert "--filter" in argv and "label=aset.owner=aset" in argv


def test_the_sweep_keeps_a_pulled_image_and_removes_a_built_one(monkeypatch) -> None:
    _sweep_with(monkeypatch, {
        ("images", "--quiet", *OWNED): "built\npulled\n",
        ("images", "--quiet", *OWNED, "--filter", "label=aset.run=now"): "",
        ("images", "--quiet", *OWNED, "--filter", "label=aset.lifetime=cache"): "pulled\n",
    })
    assert sweep("now")["images"] == ["built"]


def test_the_sweep_is_a_no_op_without_a_runtime(monkeypatch) -> None:
    monkeypatch.setattr(docker_labels.shutil, "which", lambda _name: None)
    assert sweep("now") == {"containers": [], "networks": [], "volumes": [], "images": []}


def test_the_label_arguments_are_a_docker_command_line() -> None:
    assert label_arguments("apply-1", "ingresos")[:2] == ["--label", "aset.owner=aset"]
