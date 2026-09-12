"""Check ADR 17's volume workspace against a real daemon.

[ADR 17](../../../docs/architecture/decisions/0017-the-project-lives-in-the-run.md)
claims four things a unit test with a fake runtime cannot establish: that the
project really round-trips through a named volume, that the volume really dies
with the run, that **nothing about the target project touches the operator's
disk** unless it is extracted by name, and that every container the workspace
starts carries ADR 16's labels. This checks those against the daemon.

The clone is checked separately and only when a URL is given, because it is the
one operation ADR 17 allows out to the network. What is verified there is the
shape of the exception rather than that cloning works: depth 1, and no
credential left in `.git/config` inside the volume.

Usage:
    python evaluation/benchmarks/adr17/verify_workspace.py \
        --image python:3.13-slim --output evaluation/benchmarks/adr17/results
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from engineering_team.docker_labels import (
    LIFETIME_LABEL,
    OWNER_LABEL,
    PROJECT_LABEL,
    RUN_LABEL,
)
from engineering_team.guardrails.secrets import redacted_document
from engineering_team.workspace.contract import PROJECT_MOUNT, VolumeWorkspace


def docker(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=300, check=False
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--clone-url", default="",
        help="a public repository; when given, the clone exception is checked too",
    )
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)

    run_id = f"verify-{uuid.uuid4()}"
    volume = f"aset-verify-workspace-{uuid.uuid4().hex[:8]}"
    report: dict = {"host": platform.platform(), "run_id": run_id, "checks": []}

    def record(name: str, passed: bool, detail: object = "") -> None:
        report["checks"].append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)

    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / "project"
        (source / "api").mkdir(parents=True)
        (source / "api" / "app.py").write_text("value = 1\n# needle\n", encoding="utf-8")
        (source / ".env").write_text("SECRET=do-not-read-me\n", encoding="utf-8")
        evidence = Path(scratch) / "evidence"

        workspace = VolumeWorkspace(
            volume, image=arguments.image, run_id=run_id, project="verify"
        )
        try:
            workspace.up()
            found = json.loads(
                docker("volume", "inspect", "--format", "{{json .Labels}}", volume)
                .stdout.strip() or "null"
            ) or {}
            record(
                "the run's volume carries ADR 16's labels",
                found.get(OWNER_LABEL) == "aset"
                and found.get(RUN_LABEL) == run_id
                and found.get(PROJECT_LABEL) == "verify"
                and found.get(LIFETIME_LABEL) == "run",
                found,
            )

            workspace.populate_from_host(source)
            record(
                "the project round-trips through the volume",
                workspace.read("api/app.py") == "value = 1\n# needle\n",
            )
            workspace.write("api/app.py", "value = 2\n# needle\n")
            record(
                "a write inside the volume is what the next read returns",
                workspace.read("api/app.py") == "value = 2\n# needle\n",
            )
            listed = workspace.list_paths()
            record(
                "listing shows the project and hides its secrets",
                Path("api/app.py") in listed and Path(".env") not in listed,
                sorted(str(path) for path in listed),
            )
            record(
                "search reads contents inside the volume",
                workspace.search("needle") == [Path("api/app.py")],
            )

            # The claim ADR 17 makes about the operator's disk. Checked by
            # asking for a path that is outside the project, not by trusting
            # that no code path writes one.
            refused = False
            try:
                workspace.read("../../etc/passwd")
            except ValueError:
                refused = True
            record("the workspace refuses to leave the project root", refused)

            written = workspace.extract(evidence, "api/app.py", "does-not-exist.py")
            record(
                "evidence leaves by name, and only by name",
                written == [Path("api/app.py")]
                and (evidence / "api" / "app.py").read_text() == "value = 2\n# needle\n"
                and not (evidence / "does-not-exist.py").exists(),
                [str(path) for path in written],
            )

            if arguments.clone_url:
                clone_volume = f"aset-verify-clone-{uuid.uuid4().hex[:8]}"
                cloned = VolumeWorkspace(
                    clone_volume, image=arguments.image,
                    run_id=run_id, project="verify",
                )
                try:
                    cloned.up()
                    cloned.clone(arguments.clone_url)
                    depth = docker(
                        "run", "--rm", "--network", "none",
                        "--mount", f"type=volume,source={clone_volume},target={PROJECT_MOUNT}",
                        "--workdir", str(PROJECT_MOUNT), arguments.image,
                        "git", "rev-list", "--count", "HEAD",
                    ).stdout.strip()
                    config = docker(
                        "run", "--rm", "--network", "none",
                        "--mount", f"type=volume,source={clone_volume},target={PROJECT_MOUNT}",
                        "--workdir", str(PROJECT_MOUNT), arguments.image,
                        "git", "config", "--get", "remote.origin.url",
                    ).stdout.strip()
                    record("the clone is shallow", depth == "1", {"commits": depth})
                    record(
                        "no credential is left in the cloned .git/config",
                        "@" not in config.split("//", 1)[-1].split("/", 1)[0],
                        {"origin": config},
                    )
                finally:
                    cloned.down()
        finally:
            workspace.down()

    remaining = docker("volume", "ls", "--quiet", "--filter", f"name={volume}").stdout
    record("the volume dies with the run", volume not in remaining)

    # Nothing of the project should be on the operator's disk. The scratch
    # directory is gone; what would remain is a stray ASET volume.
    leftover = docker(
        "volume", "ls", "--quiet", "--filter", f"label={RUN_LABEL}={run_id}"
    ).stdout.split()
    record(
        "no resource of this run survives it",
        not leftover,
        leftover,
    )

    report["finished"] = True
    (arguments.output / "verification.json").write_text(
        json.dumps(redacted_document(report), indent=2) + "\n", encoding="utf-8"
    )
    failed = [item["check"] for item in report["checks"] if not item["passed"]]
    print(f"\nwritten: {arguments.output / 'verification.json'}")
    if failed:
        print(f"{len(failed)} check(s) failed: {failed}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
