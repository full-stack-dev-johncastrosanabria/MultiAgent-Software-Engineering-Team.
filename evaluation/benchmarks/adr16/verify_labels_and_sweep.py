"""Check ADR 16 against a real daemon, including what it promises *not* to touch.

[ADR 16](../../../docs/architecture/decisions/0016-every-docker-resource-carries-its-run.md)
makes two kinds of claim, and only one of them is easy to test. That every
resource a run creates carries `aset.owner`, `aset.run`, `aset.project` and
`aset.lifetime` is checkable by inspecting the resource. That the sweep removes
*only* what ASET owns is the claim that matters on a laptop which is also the
operator's work machine, and a unit test cannot make it: it needs a host with
other people's containers on it.

So this takes a full inventory of the daemon before and after, and reports the
difference. A check that passes while something unlabelled disappeared is a
failed check, whatever the assertions say.

Refusals built in, because this script is destructive by design:

  * it aborts if the daemon already holds run-lifetime resources from a run
    other than this one -- sweeping then could reap a live run's work, which is
    precisely the mistake ADR 16 names;
  * `--dry-run` takes the inventory and the labelling evidence and stops before
    the sweep.

Usage:
    python evaluation/benchmarks/adr16/verify_labels_and_sweep.py \
        --output evaluation/benchmarks/adr16/results
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import uuid
from pathlib import Path

from engineering_team.docker_labels import (
    LIFETIME_LABEL,
    OWNER_FILTER,
    OWNER_LABEL,
    PROJECT_LABEL,
    RUN_LABEL,
    RUN_LIFETIME,
    label_arguments,
    sweep,
)
from engineering_team.guardrails.secrets import redacted_document

EXPECTED_LABELS = (OWNER_LABEL, RUN_LABEL, PROJECT_LABEL, LIFETIME_LABEL)


def docker(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=120, check=False
    )


def inventory() -> dict[str, list[str]]:
    """Every container, network and volume on the daemon, ASET's or not."""
    return {
        "containers": sorted(docker("ps", "-a", "--quiet").stdout.split()),
        "networks": sorted(docker("network", "ls", "--quiet").stdout.split()),
        "volumes": sorted(docker("volume", "ls", "--quiet").stdout.split()),
    }


def labels_of(kind: str, name: str) -> dict[str, str]:
    template = "{{json .Config.Labels}}" if kind == "container" else "{{json .Labels}}"
    completed = docker("inspect", "--format", template, name) if kind == "container" else (
        docker(kind, "inspect", "--format", template, name)
    )
    if completed.returncode != 0:
        return {}
    try:
        return json.loads(completed.stdout.strip() or "null") or {}
    except json.JSONDecodeError:
        return {}


def foreign_runs(this_run: str) -> set[str]:
    """Run-lifetime resources on this host that belong to some other run."""
    found: set[str] = set()
    for kind, listing in (
        ("container", ["ps", "-a", "--quiet"]),
        ("network", ["network", "ls", "--quiet"]),
        ("volume", ["volume", "ls", "--quiet"]),
    ):
        completed = docker(
            *listing, "--filter", f"label={OWNER_FILTER}",
            "--filter", f"label={LIFETIME_LABEL}={RUN_LIFETIME}",
        )
        for name in completed.stdout.split():
            owner = labels_of(kind, name).get(RUN_LABEL, "")
            if owner and owner != this_run:
                found.add(owner)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="python:3.13-slim")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)

    run_id = f"verify-{uuid.uuid4()}"
    dead_run = f"verify-dead-{uuid.uuid4()}"
    report: dict = {
        "host": platform.platform(),
        "run_id": run_id,
        "checks": [],
        "finished": False,
    }

    def record(name: str, passed: bool, detail: object = "") -> None:
        report["checks"].append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)

    intruders = foreign_runs(run_id)
    if intruders:
        print(
            "refusing to sweep: this host holds run-lifetime resources owned by "
            f"{sorted(intruders)}. Another ASET run may be live.",
            file=sys.stderr,
        )
        return 2

    before = inventory()
    report["inventory_before"] = {k: len(v) for k, v in before.items()}

    # -- what a run creates carries its run -------------------------------
    #
    # Created here with the same helper the production code uses, so the check
    # is of the label set itself rather than of a copy of it.
    mine = f"aset-verify-{uuid.uuid4().hex[:8]}"
    theirs = f"not-aset-verify-{uuid.uuid4().hex[:8]}"
    orphan = f"aset-orphan-{uuid.uuid4().hex[:8]}"
    created: list[tuple[str, str]] = []
    try:
        docker("volume", "create", *label_arguments(run_id, "verify"), mine)
        created.append(("volume", mine))
        found = labels_of("volume", mine)
        record(
            "a volume the current run creates carries all four labels",
            all(found.get(label) for label in EXPECTED_LABELS)
            and found.get(RUN_LABEL) == run_id
            and found.get(PROJECT_LABEL) == "verify",
            found,
        )

        # A resource from a run that is no longer alive: what the sweep exists
        # for, since ordinary teardown cannot cover a crash.
        docker("volume", "create", *label_arguments(dead_run, "verify"), orphan)
        created.append(("volume", orphan))

        # Something that is not ASET's. The sweep must not learn about it.
        docker("volume", "create", theirs)
        created.append(("volume", theirs))

        if arguments.dry_run:
            record("sweep skipped (--dry-run)", True)
        else:
            swept = sweep(run_id)
            report["swept"] = swept
            after = inventory()
            report["inventory_after"] = {k: len(v) for k, v in after.items()}

            record(
                "the sweep reaps a resource left by a run that is no longer alive",
                orphan not in after["volumes"],
                {"orphan": orphan},
            )
            record(
                "the sweep leaves the current run's own resources alone",
                mine in after["volumes"],
                {"mine": mine},
            )
            record(
                "the sweep leaves a resource that is not ASET's alone",
                theirs in after["volumes"],
                {"theirs": theirs},
            )

            # The claim that matters on an operator's laptop, checked against
            # the whole daemon rather than against the resources this script
            # happens to know about.
            collateral = {
                kind: [
                    name for name in before[kind]
                    if name not in after[kind] and name != orphan
                ]
                for kind in before
            }
            report["collateral"] = collateral
            record(
                "nothing that existed before the sweep and was not ASET's disappeared",
                not any(collateral.values()),
                collateral,
            )
    finally:
        for kind, name in created:
            docker(kind, "rm", "--force", name)
        report["finished"] = True
        (arguments.output / "report.json").write_text(
            json.dumps(redacted_document(report), indent=2) + "\n", encoding="utf-8"
        )

    failed = [item["check"] for item in report["checks"] if not item["passed"]]
    print(f"\nwritten: {arguments.output / 'report.json'}")
    if failed:
        print(f"{len(failed)} check(s) failed: {failed}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
