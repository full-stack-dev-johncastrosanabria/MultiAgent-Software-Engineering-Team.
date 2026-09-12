"""Check ADR 18's blocking prerequisite against real git and a real daemon.

[ADR 18](../../../docs/architecture/decisions/0018-missing-infrastructure-is-a-blocking-prerequisite.md)
turns a project that declares no infrastructure into two pull requests: one that
contains infrastructure and nothing else, and one stacked on it that says what
its evidence is worth. The unit tests drive that with fakes. What they cannot
show is what a reviewer would actually receive, so this runs the real
`GitDelivery` against a real repository with a local bare remote, and brings the
derived topology up on the real daemon.

The project used here is a fixture, not the operator's work: a Spring service
whose `application.yaml` names MySQL **and carries a plaintext password**, which
is the case ADR 13 and ADR 18 both have an opinion about. That password is what
the secret checks below look for in the delivered files, in the pull request
body and in the commit.

One thing this reports rather than asserts: the compose file brought up is the
`run` rendering, and the compose file delivered is the `delivery` rendering.
They are two outputs of the same inference, and nothing here proves the
delivered one starts. ADR 18 is written as if bringing infrastructure up
validated what the pull request contains; it does not. Two checks narrow that
gap without closing it: the delivered file and its template are handed to the
runtime for `compose config`, and the gate that refuses a file the runtime
rejects is exercised against a template deliberately missing a variable.

Usage:
    python evaluation/benchmarks/adr18/verify_infrastructure_prerequisite.py \
        --output evaluation/benchmarks/adr18/results
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path

from engineering_team import infrastructure_prerequisite as prerequisites
from engineering_team.delivery import DeliveryRefused, GitDelivery, Proposal
from engineering_team.delivery_check import validate_delivered_compose
from engineering_team.guardrails.secrets import redacted_document
from engineering_team.services import ServiceStack

PASSWORD = "sup3rs3cret-fixture-password"
APPLICATION_YAML = f"""spring:
  datasource:
    url: jdbc:mysql://localhost:3306/billing?useSSL=false
    username: billing
    password: {PASSWORD}
"""


def git(repository: Path, *arguments: str) -> str:
    finished = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True, text=True, timeout=120, check=True,
    )
    return finished.stdout.strip()


def build_project(root: Path) -> None:
    """A project that needs MySQL and declares no compose file."""
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yaml").write_text(
        APPLICATION_YAML, encoding="utf-8"
    )
    (root / "README.md").write_text("# billing\n", encoding="utf-8")
    git(root, "init", "--quiet", "--initial-branch=main")
    git(root, "config", "user.email", "verify@example.invalid")
    git(root, "config", "user.name", "ADR 18 verification")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "feat: the project before the run")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--skip-daemon", action="store_true",
        help="skip bringing the derived topology up (no Docker available)",
    )
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)

    run_id = f"verify-{uuid.uuid4().hex[:8]}"
    report: dict = {"host": platform.platform(), "run_id": run_id, "checks": [],
                    "notes": []}

    def record(name: str, passed: bool, detail: object = "") -> None:
        report["checks"].append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "billing"
        root.mkdir()
        build_project(root)
        remote = Path(scratch) / "remote.git"
        subprocess.run(
            ["git", "init", "--quiet", "--bare", str(remote)], check=True, timeout=60
        )
        git(root, "remote", "add", "origin", str(remote))
        git(root, "push", "--quiet", "origin", "main")

        services = ServiceStack(root, run_id)
        prerequisite = prerequisites.detect(services, root)
        record(
            "a project with no compose file is detected as a prerequisite",
            prerequisite is not None
            and prerequisite.engines == ("mysql",)
            and "src/main/resources/application.yaml" in prerequisite.read_from,
            {
                "engines": list(prerequisite.engines) if prerequisite else None,
                "read_from": list(prerequisite.read_from) if prerequisite else None,
            },
        )
        if prerequisite is None:
            return 1

        delivered = prerequisites.deliver(
            root, prerequisite, run_id=run_id, backend=None, confirmed=True,
            git=GitDelivery(),
        )
        changed = git(
            root, "diff", "--name-status", f"main..{delivered.branch}"
        ).splitlines()
        record(
            "the infrastructure branch adds compose and extends .env.example, "
            "and touches nothing else",
            sorted(changed) == sorted(["A\t.env.example", "A\tdocker-compose.yml"]),
            changed,
        )
        record(
            "the branch carries no application code change",
            not any("src/" in line for line in changed),
            changed,
        )

        compose_delivered = git(root, "show", f"{delivered.branch}:docker-compose.yml")
        env_delivered = git(root, "show", f"{delivered.branch}:.env.example")
        proposal = prerequisite.proposal(run_id)
        message = git(root, "log", "-1", "--format=%B", delivered.branch)
        leaked = {
            "docker-compose.yml": PASSWORD in compose_delivered,
            ".env.example": PASSWORD in env_delivered,
            "body": PASSWORD in (proposal.body if proposal else ""),
            "commit message": PASSWORD in message,
        }
        record(
            "the project's plaintext password reaches none of the delivered artefacts",
            not any(leaked.values()),
            leaked,
        )
        record(
            "credentials are delivered as variables with a template",
            "${" in compose_delivered and "MYSQL" in env_delivered,
            {"env_example": env_delivered.splitlines()},
        )

        if not arguments.skip_daemon:
            # The two artefacts as a reviewer receives them -- read back out of
            # the branch, not out of the objects that produced it -- handed to
            # the runtime. Nothing is started: `compose config` resolves the
            # schema and the substitution and stops there.
            aligned = validate_delivered_compose(compose_delivered, env_delivered)
            record(
                "the delivered compose resolves against the delivered .env.example",
                aligned.performed and aligned.valid,
                {
                    "performed": aligned.performed,
                    "valid": aligned.valid,
                    "error": aligned.error,
                    "occupied_ports": list(aligned.occupied_ports),
                },
            )

            # The negative case, which is the only thing that proves the gate is
            # a gate: a template that no longer declares a variable the compose
            # file interpolates is the exact failure the reviewer would meet as
            # `variable is not set`. `deliver` is asked, not the checker, so a
            # refusal has to travel all the way to `DeliveryRefused`.
            dropped = [
                line for line in env_delivered.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ][:1]
            starved = replace(
                prerequisite,
                env_example="\n".join(
                    line for line in env_delivered.splitlines() if line not in dropped
                ) + "\n",
            )
            refused = ""
            try:
                prerequisites.deliver(
                    root, starved,
                    run_id=f"{run_id}-starved", backend=None, confirmed=True,
                    git=GitDelivery(),
                )
            except DeliveryRefused as refusal:
                refused = str(refusal)
            record(
                "a delivered compose whose template lost a variable is refused",
                bool(refused),
                {"removed": dropped, "refusal": refused},
            )

        # The functional pull request, stacked on the one above.
        functional = Proposal(
            branch="aset/apply-verify-18",
            title="fix: the functional work that needed the database",
            body=prerequisites.stacked_body(
                "The suite is green.", delivered
            ),
            files={"src/main/java/Fixed.java": "// fixed\n"},
            run_id=run_id,
        )
        functional_branch = GitDelivery().push(
            root, functional, confirmed=True, base=delivered.branch
        )
        base_point = git(root, "merge-base", delivered.branch, functional_branch)
        infrastructure_tip = git(root, "rev-parse", delivered.branch)
        record(
            "the functional branch is cut from the infrastructure branch, not from main",
            base_point == infrastructure_tip,
            {"merge_base": base_point, "infrastructure_tip": infrastructure_tip},
        )
        record(
            "the stacked body states the evidence describes unreviewed infrastructure",
            "no human has reviewed" in functional.body
            and "re-run" in functional.body
            and delivered.branch in functional.body,
        )
        record(
            "both branches reached the remote",
            {delivered.branch, functional_branch}
            <= {
                line.split()[-1].removeprefix("refs/heads/")
                for line in git(root, "ls-remote", "--heads", "origin").splitlines()
            },
        )

        if not arguments.skip_daemon:
            started = time.monotonic()
            try:
                services.up(time.monotonic() + 420)
                running = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}\t{{.Label \"aset.run\"}}",
                     "--filter", f"label=aset.run={run_id}"],
                    capture_output=True, text=True, timeout=60, check=False,
                ).stdout.split()
                record(
                    "the prerequisite comes up and its containers carry the run",
                    bool(running),
                    {"containers": running, "seconds": round(time.monotonic() - started, 2)},
                )
            finally:
                services.down()
            report["notes"].append(
                "The topology brought up is the `run` rendering (service-name "
                "hosts, no published ports); the file delivered is the `delivery` "
                "rendering (localhost ports, ${VAR} credentials). Bringing the "
                "run one up does not prove the delivered one starts, so a port "
                "collision or an unset variable in the delivered file would reach "
                "the reviewer unexercised."
            )
            report["notes"].append(
                "That gap is narrower than it was and has not closed. The two "
                "checks above hand the delivered file itself to the runtime, so "
                "its schema and its variable substitution are now resolved and a "
                "published port already busy here is named in the body. Nothing "
                "above pulls an image, starts a container, or waits for a "
                "healthcheck on the delivered rendering: `compose config` is the "
                "whole of the coverage."
            )
            report["notes"].append(
                "Both renderings come from the same inference, so the engine and "
                "the pinned digest are shared; what is untested is only the part "
                "that differs."
            )
        else:
            report["notes"].append(
                "The daemon arm was skipped by --skip-daemon, and with it the "
                "two delivery-validation checks: both ask a container runtime, "
                "and --skip-daemon is how this runner is told there is none."
            )

    (arguments.output / "verification.json").write_text(
        json.dumps(redacted_document(report), indent=2) + "\n", encoding="utf-8"
    )
    failed = [item["check"] for item in report["checks"] if not item["passed"]]
    print(f"\nwritten: {arguments.output / 'verification.json'}")
    for note in report["notes"]:
        print(f"note: {note}")
    if failed:
        print(f"{len(failed)} check(s) failed: {failed}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
