"""Measure the two places a project can live, because ADR 17 refuses to assume.

ADR 17 chooses a run-scoped named volume over a copy on the operator's disk, and
says in the same breath that the choice is not validated until it is measured:
on macOS the file sharing layer between the host and the Linux VM is the very
thing that could make the volume slower rather than faster, and a direction
taken on belief is how a project acquires a performance regression it cannot
explain later.

Three arms, so that the numbers answer the actual question:

  host      the work done natively on the operator's disk, as ASET does today
            when `create_run_copy` produces a directory and tools run over it.
            Not reachable under ADR 15 -- it is the floor, not a candidate.
  bind      the same work inside a container over a bind-mounted host directory.
            This is today's container path and the honest comparison point.
  volume    the same work inside a container over a named volume. ADR 17's
            proposal.

The workload is deliberately the shape ASET's own work has: many small files,
a full listing, a content search, and a batch of reads and writes. A single
large file would measure throughput, which is not what is in doubt.

Usage:
    python evaluation/benchmarks/adr17/measure_workspace.py \
        --image python:3.13-slim --output evaluation/benchmarks/adr17/results
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from engineering_team.workspace.contract import PROJECT_MOUNT

# Roughly the shape of a small service repository: enough files that per-file
# cost dominates, few enough that a run finishes in seconds.
FILE_COUNT = 600
LINES_PER_FILE = 40


def build_tree(root: Path) -> None:
    """Write a synthetic project. Synthetic on purpose: reproducible anywhere."""
    body = "\n".join(f"    value_{index} = {index}" for index in range(LINES_PER_FILE))
    for index in range(FILE_COUNT):
        package = root / f"package_{index % 20}"
        package.mkdir(parents=True, exist_ok=True)
        (package / f"module_{index}.py").write_text(
            f"class Module{index}:\n{body}\n\n# needle marker {index}\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)


LIST_COMMAND = "find . -type f -name '*.py' | wc -l"
SEARCH_COMMAND = "grep -rilF 'needle marker 42' . | wc -l"
READ_COMMAND = "for f in $(find . -name 'module_*.py' | head -200); do cat \"$f\" > /dev/null; done"
WRITE_COMMAND = (
    "for i in $(seq 1 200); do echo edited > written_$i.py; done"
)

OPERATIONS = {
    # A container that does nothing, so the arms can be read at all: on this
    # host `docker run` costs more than any of the operations below, and without
    # subtracting it the two container arms look identical because they mostly
    # are -- identical startup with a rounding error of file IO on top.
    "noop": "true",
    "list": LIST_COMMAND,
    "search": SEARCH_COMMAND,
    "read_200": READ_COMMAND,
    "write_200": WRITE_COMMAND,
}


def timed(function) -> float:
    start = time.monotonic()
    function()
    return time.monotonic() - start


def run_host(root: Path, command: str) -> None:
    subprocess.run(["sh", "-c", command], cwd=root, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_in_container(mount: str, image: str, command: str) -> None:
    completed = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none",
            "--mount", mount, "--workdir", str(PROJECT_MOUNT),
            image, "sh", "-c", command,
        ],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-400:])


def measure_arm(name: str, invoke, repeats: int) -> dict:
    """Run every operation `repeats` times. Median reported; spread retained."""
    samples: dict[str, list[float]] = {}
    for operation, command in OPERATIONS.items():
        samples[operation] = [
            timed(lambda bound=command: invoke(bound)) for _ in range(repeats)
        ]
    medians = {
        operation: statistics.median(values) for operation, values in samples.items()
    }
    overhead = medians["noop"]
    return {
        "arm": name,
        "median_seconds": {
            operation: round(value, 4) for operation, value in medians.items()
        },
        # What the operation itself cost, once the container's own startup is
        # taken out. Floored at zero: a negative number here means the two
        # medians differ by less than the startup noise, which is the same
        # statement as "too small to measure".
        "net_seconds": {
            operation: round(max(value - overhead, 0.0), 4)
            for operation, value in medians.items() if operation != "noop"
        },
        "samples_seconds": {
            operation: [round(value, 4) for value in values]
            for operation, values in samples.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="image the containers run")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)

    volume = f"aset-measure-{uuid.uuid4().hex[:8]}"
    report = {
        "host": platform.platform(),
        "docker": subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}} {{.Server.Os}}"],
            capture_output=True, text=True, check=False,
        ).stdout.strip(),
        "file_count": FILE_COUNT,
        "repeats": arguments.repeats,
        "arms": [],
    }

    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / "project"
        source.mkdir()
        build_tree(source)

        report["arms"].append(measure_arm(
            "host", lambda command: run_host(source, command), arguments.repeats,
        ))

        bind = f"type=bind,source={source},target={PROJECT_MOUNT}"
        report["arms"].append(measure_arm(
            "bind",
            lambda command: run_in_container(bind, arguments.image, command),
            arguments.repeats,
        ))

        mount = f"type=volume,source={volume},target={PROJECT_MOUNT}"
        subprocess.run(["docker", "volume", "create", volume],
                       capture_output=True, check=True)
        try:
            populate = timed(lambda: subprocess.run(
                [
                    "docker", "run", "--rm", "--network", "none",
                    "--mount", f"type=bind,source={source},target=/aset/source,readonly",
                    "--mount", mount,
                    arguments.image, "sh", "-c", f"cp -a /aset/source/. {PROJECT_MOUNT}/",
                ],
                capture_output=True, check=True,
            ))
            report["volume_populate_seconds"] = round(populate, 4)
            report["arms"].append(measure_arm(
                "volume",
                lambda command: run_in_container(mount, arguments.image, command),
                arguments.repeats,
            ))
        finally:
            subprocess.run(["docker", "volume", "rm", "--force", volume],
                           capture_output=True, check=False)

    destination = arguments.output / "measurement.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["arms"], indent=2))
    print(f"\nwritten: {destination}")


if __name__ == "__main__":
    main()
