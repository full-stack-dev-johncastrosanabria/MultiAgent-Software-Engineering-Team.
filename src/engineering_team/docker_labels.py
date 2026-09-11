"""What every Docker resource a run creates carries, and the sweep that reads it.

[ADR 16](../../docs/architecture/decisions/0016-every-docker-resource-carries-its-run.md)
decides the labels: `aset.owner` says who created the resource, `aset.run` says
which run, `aset.project` says which project -- stable across runs, unlike the
run id -- and `aset.lifetime` separates what is reaped without exception from
what a later run may reuse.

The label is also what makes deletion safe. Every query here filters on
`aset.owner=aset` first, so a resource nobody labelled is never a candidate: the
sweep is deliberately biased toward leaving unlabelled state alone, because the
cost of deleting a person's database is not comparable to the cost of leaving a
stale volume behind.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

OWNER = "aset"
OWNER_LABEL = "aset.owner"
RUN_LABEL = "aset.run"
PROJECT_LABEL = "aset.project"
LIFETIME_LABEL = "aset.lifetime"

# Anything that runs or holds state. Reaped without exception.
RUN_LIFETIME = "run"
# Content a later run can reuse without inheriting anything: pulled base images,
# package caches. Nothing stateful is ever this.
CACHE_LIFETIME = "cache"

OWNER_FILTER = f"{OWNER_LABEL}={OWNER}"

_SLUG = re.compile(r"[^a-z0-9-]+")


def project_slug(root: str | Path) -> str:
    """The name a person recognises the project by.

    The directory the project was cloned or opened into, sanitised to what
    compose accepts as a project name. It is not the run id on purpose: the run
    id changes every run and identifies nothing to a human reading `docker ps`.
    """
    slug = _SLUG.sub("-", Path(root).resolve().name.lower()).strip("-")
    return slug or "project"


def labels(
    run_id: str, project: str = "", *, lifetime: str = RUN_LIFETIME
) -> dict[str, str]:
    """The labels one resource carries, as a mapping."""
    if lifetime not in (RUN_LIFETIME, CACHE_LIFETIME):
        raise ValueError(f"unknown aset.lifetime: {lifetime!r}")
    values = {
        OWNER_LABEL: OWNER,
        RUN_LABEL: run_id or "unknown",
        LIFETIME_LABEL: lifetime,
    }
    if project:
        values[PROJECT_LABEL] = project
    return values


def label_arguments(
    run_id: str, project: str = "", *, lifetime: str = RUN_LIFETIME
) -> list[str]:
    """The same labels as `--label key=value` pairs for a docker command line."""
    pairs: list[str] = []
    for key, value in labels(run_id, project, lifetime=lifetime).items():
        pairs += ["--label", f"{key}={value}"]
    return pairs


def compose_label_lines(
    run_id: str, project: str = "", *, indent: str, lifetime: str = RUN_LIFETIME
) -> list[str]:
    """The same labels as the `labels:` block of a compose element.

    Compose is given these in the override document ASET writes, not in the
    project's own file: the project's file is evidence about how it deploys, and
    ASET's bookkeeping does not belong in it.
    """
    lines = [f"{indent}labels:"]
    for key, value in labels(run_id, project, lifetime=lifetime).items():
        lines.append(f"{indent}  {key}: {value}")
    return lines


def _listed(runtime: str, arguments: list[str]) -> set[str]:
    try:
        completed = subprocess.run(
            [runtime, *arguments],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if completed.returncode != 0:
        return set()
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def _owned(runtime: str, kind: list[str], current_run_id: str) -> list[str]:
    """Everything ASET owns of one kind, minus what the current run owns."""
    everything = _listed(runtime, [*kind, "--filter", f"label={OWNER_FILTER}"])
    mine = (
        _listed(runtime, [*kind, "--filter", f"label={OWNER_FILTER}",
                          "--filter", f"label={RUN_LABEL}={current_run_id}"])
        if current_run_id else set()
    )
    return sorted(everything - mine)


def _removed(runtime: str, command: list[str], names: list[str]) -> list[str]:
    gone: list[str] = []
    for name in names:
        try:
            completed = subprocess.run(
                [runtime, *command, name],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            gone.append(name)
    return gone


def sweep(current_run_id: str = "", *, runtime: str = "docker") -> dict[str, list[str]]:
    """Remove what ASET labelled and no live run still owns.

    A run reaps what it labelled through the ordinary teardown; this is what
    makes reaping possible *after a crash*, which is the case the teardown
    cannot cover. Anything whose `aset.run` is the current run is left alone --
    reaping by owner alone would delete a concurrent run's resources, which
    [ADR 16](../../docs/architecture/decisions/0016-every-docker-resource-carries-its-run.md)
    names as the way to get this wrong.

    Order matters: a network with a container attached cannot be removed, and a
    volume in use by a container cannot either.
    """
    report: dict[str, list[str]] = {
        "containers": [], "networks": [], "volumes": [], "images": []
    }
    if shutil.which(runtime) is None:
        return report
    report["containers"] = _removed(
        runtime, ["rm", "--force"],
        _owned(runtime, ["ps", "-a", "--quiet"], current_run_id),
    )
    report["networks"] = _removed(
        runtime, ["network", "rm"],
        _owned(runtime, ["network", "ls", "--quiet"], current_run_id),
    )
    report["volumes"] = _removed(
        runtime, ["volume", "rm", "--force"],
        _owned(runtime, ["volume", "ls", "--quiet"], current_run_id),
    )
    # Only images a run built. An image a run pulled is labelled `cache` on
    # purpose and survives: re-pulling postgres for every run trades disk for
    # bandwidth, and that is a bad trade.
    built = set(_owned(runtime, ["images", "--quiet"], current_run_id))
    cached = _listed(
        runtime,
        ["images", "--quiet", "--filter", f"label={OWNER_FILTER}",
         "--filter", f"label={LIFETIME_LABEL}={CACHE_LIFETIME}"],
    )
    report["images"] = _removed(
        runtime, ["image", "rm", "--force"], sorted(built - cached)
    )
    return report
