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
from typing import TypedDict

from engineering_team.contracts.enums import ErrorCode

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


class RuntimeUnresponsive(Exception):
    """`docker` (or whichever runtime was named) did not answer in time.

    Raised out of `_listed`/`_removed` so `sweep` can stop at the very first
    one instead of enduring the same timeout for every remaining resource
    kind. Deliberately distinct from the `(OSError, SubprocessError)` case
    below: a missing binary or a malformed invocation means there is nothing
    to report, but a hang means the question was never answered, which is a
    different fact and must not collapse into the same empty result (A-13,
    B-11 -- a hung daemon is not an absent one).
    """


class SweepReport(TypedDict):
    """What one sweep removed, or why it could not look.

    `error_code` is `None` when the sweep queried the runtime for every
    resource kind, whether or not anything came back -- an empty `containers`
    list under `error_code=None` truly means "nothing to clean" for that
    kind. `ErrorCode.INFRASTRUCTURE_ERROR` means the runtime stopped
    answering partway through: everything up to that point is real (a kind
    already swept keeps its actual removals), but any kind the sweep never
    reached is empty because it was never looked at, not because there was
    nothing there. A caller must not read the empty kinds under
    `INFRASTRUCTURE_ERROR` as "ASET owns nothing" -- only as "unknown". This
    reuses the vocabulary `ToolResult.error_code` and `ServiceStartupError.code`
    already carry elsewhere, rather than a new marker every caller would have
    to learn to compare against.
    """

    containers: list[str]
    networks: list[str]
    volumes: list[str]
    images: list[str]
    error_code: ErrorCode | None


def _listed(runtime: str, arguments: list[str], *, timeout: float = 60) -> set[str]:
    try:
        completed = subprocess.run(
            [runtime, *arguments],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeUnresponsive(
            f"{runtime} did not answer within {timeout}s: {arguments}"
        ) from exc
    except (OSError, subprocess.SubprocessError):
        return set()
    if completed.returncode != 0:
        return set()
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def _owned(
    runtime: str, kind: list[str], current_run_id: str, *, timeout: float = 60
) -> list[str]:
    """Everything ASET owns of one kind, minus what the current run owns."""
    everything = _listed(
        runtime, [*kind, "--filter", f"label={OWNER_FILTER}"], timeout=timeout
    )
    mine = (
        _listed(runtime, [*kind, "--filter", f"label={OWNER_FILTER}",
                          "--filter", f"label={RUN_LABEL}={current_run_id}"],
                timeout=timeout)
        if current_run_id else set()
    )
    return sorted(everything - mine)


def _removed(
    runtime: str, command: list[str], names: list[str], *, timeout: float = 120
) -> list[str]:
    gone: list[str] = []
    for name in names:
        try:
            completed = subprocess.run(
                [runtime, *command, name],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeUnresponsive(
                f"{runtime} did not answer within {timeout}s: {command} {name}"
            ) from exc
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            gone.append(name)
    return gone


def sweep(
    current_run_id: str = "", *, runtime: str = "docker", timeout: float = 60
) -> SweepReport:
    """Remove what ASET labelled and no live run still owns.

    A run reaps what it labelled through the ordinary teardown; this is what
    makes reaping possible *after a crash*, which is the case the teardown
    cannot cover. Anything whose `aset.run` is the current run is left alone --
    reaping by owner alone would delete a concurrent run's resources, which
    [ADR 16](../../docs/architecture/decisions/0016-every-docker-resource-carries-its-run.md)
    names as the way to get this wrong.

    Order matters: a network with a container attached cannot be removed, and a
    volume in use by a container cannot either.

    A hung runtime is not an absent one. `shutil.which` finding nothing below
    returns immediately with `error_code=None`: there truly is nothing to
    look at. But once a runtime is found, this makes ~8 listing calls (one or
    two per resource kind) and each one can wait up to `timeout` seconds; a
    daemon that stops answering mid-sweep used to cost minutes of silent
    waiting and then report `error_code=None` with everything empty, as if it
    had looked and found nothing (A-13, B-11). `RuntimeUnresponsive` from the
    first `_listed`/`_removed` call ends the sweep right there instead --
    keeping whatever kinds of resource were already swept before the hang, so
    a hang on, say, the network sweep does not also erase the record that the
    container sweep genuinely ran and removed something.
    """
    empty: SweepReport = {
        "containers": [], "networks": [], "volumes": [], "images": [],
        "error_code": None,
    }
    if shutil.which(runtime) is None:
        return empty
    remove_timeout = timeout * 2
    report: SweepReport = dict(empty)  # type: ignore[assignment]
    try:
        report["containers"] = _removed(
            runtime, ["rm", "--force"],
            _owned(runtime, ["ps", "-a", "--quiet"], current_run_id, timeout=timeout),
            timeout=remove_timeout,
        )
        report["networks"] = _removed(
            runtime, ["network", "rm"],
            _owned(runtime, ["network", "ls", "--quiet"], current_run_id, timeout=timeout),
            timeout=remove_timeout,
        )
        report["volumes"] = _removed(
            runtime, ["volume", "rm", "--force"],
            _owned(runtime, ["volume", "ls", "--quiet"], current_run_id, timeout=timeout),
            timeout=remove_timeout,
        )
        # Only images a run built. An image a run pulled is labelled `cache` on
        # purpose and survives: re-pulling postgres for every run trades disk for
        # bandwidth, and that is a bad trade.
        built = set(
            _owned(runtime, ["images", "--quiet"], current_run_id, timeout=timeout)
        )
        cached = _listed(
            runtime,
            ["images", "--quiet", "--filter", f"label={OWNER_FILTER}",
             "--filter", f"label={LIFETIME_LABEL}={CACHE_LIFETIME}"],
            timeout=timeout,
        )
        report["images"] = _removed(
            runtime, ["image", "rm", "--force"], sorted(built - cached),
            timeout=remove_timeout,
        )
    except RuntimeUnresponsive:
        # Whatever kind already completed stays real: only the kind that
        # hung, and any kind after it, are still at their initial empty
        # value -- which `error_code` says to read as "not looked at", not
        # as "nothing there".
        return {**report, "error_code": ErrorCode.INFRASTRUCTURE_ERROR}
    return report
