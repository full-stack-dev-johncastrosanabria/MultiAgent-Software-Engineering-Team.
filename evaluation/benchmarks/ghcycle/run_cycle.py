"""One target repository through the whole cycle, scored stage by stage.

A binary pass/fail cannot tell a slow MySQL from an architectural hole. Six
stages are scored independently, so a red one names a place to look.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from engineering_team.guardrails.secrets import redacted_document

RESULTS = Path(__file__).resolve().parent / "results"


# ADR 16 labels containers, named volumes and networks alike, and its own
# inventory measured volumes as the bulk of the leak. Asking only about
# containers would read green with a stale volume still standing.
_RESOURCE_QUERIES = (
    ("container", ["docker", "ps", "-a", "--format", "{{.Names}}"]),
    ("volume", ["docker", "volume", "ls", "--format", "{{.Name}}"]),
    ("network", ["docker", "network", "ls", "--format", "{{.Name}}"]),
)


def _labelled_resources() -> list[str]:
    """Name every resource ASET labelled as its own, across resource kinds.

    The filter is `aset.owner=aset` everywhere: a resource nobody labelled is
    never reported, so an unrelated container on the machine stays invisible.
    """
    found: list[str] = []
    for kind, query in _RESOURCE_QUERIES:
        completed = subprocess.run(
            [*query, "--filter", "label=aset.owner=aset"],
            capture_output=True, text=True, check=False,
        )
        found.extend(
            f"{kind}/{line.strip()}"
            for line in completed.stdout.splitlines()
            if line.strip()
        )
    return found


def _score(evidence: dict, *, delivered: bool) -> dict[str, dict]:
    """Read the run's own evidence and say which stages hold.

    Nothing here re-runs anything: the run already answered these questions, and
    a second source of truth is a second thing to keep correct.
    """
    review = evidence.get("review") or {}
    written = evidence.get("files_written") or []
    prerequisite = evidence.get("infrastructure_prerequisite")
    stages: dict[str, dict] = {}

    stages["clone"] = {
        "passed": bool(evidence),
        "detail": "the run produced evidence, so it had a checkout to work in",
    }
    stages["infrastructure"] = {
        "passed": (
            prerequisite is None
            or bool(evidence.get("infrastructure_branch"))
            or not delivered
        ),
        "detail": json.dumps(prerequisite),
        "branch": evidence.get("infrastructure_branch"),
        "error": evidence.get("infrastructure_delivery_error"),
    }
    outcomes = evidence.get("tool_outcomes") or []
    unavailable = [
        item for item in outcomes if item.get("status") == "UNAVAILABLE"
    ]
    ran_tests = any(item["tool"] == "run_tests" for item in outcomes)
    # A FAIL does not turn the stage red: a TDD loop is meant to go red before it
    # goes green, so failures are normal here. They are counted anyway, because
    # a run whose tests failed every iteration otherwise reads as a clean PASS.
    failed = [item for item in outcomes if item.get("status") == "FAIL"]
    failed_by_tool = {
        tool: sum(1 for item in failed if item.get("tool") == tool)
        for tool in sorted({item.get("tool") for item in failed})
    }
    stages["execute"] = {
        # Tools ran, none degraded, and the test tool is among them: a run whose
        # containers never came up produces an empty list and reads as red.
        "passed": bool(outcomes) and not unavailable and ran_tests,
        "detail": (
            f"{len(outcomes)} tool outcomes, {len(unavailable)} unavailable, "
            f"{len(failed)} failed"
        ),
        "unavailable": unavailable[:5],
        "failed_by_tool": failed_by_tool,
    }
    stages["spec"] = {
        "passed": bool(written) and review.get("status") == "APPROVED",
        "detail": f"{len(written)} files written, reviewer said {review.get('status')}",
        "files_written": written,
    }
    stages["delivery"] = {
        "passed": (not delivered) or bool(evidence.get("delivery_pr_url")),
        "pull_request": evidence.get("delivery_pr_url"),
        "branch": evidence.get("delivery_branch"),
        "error": evidence.get("delivery_error") or evidence.get("delivery_blocked"),
        "skipped": not delivered,
    }
    leftovers = _labelled_resources()
    stages["hygiene"] = {
        "passed": not leftovers,
        "leftover_labelled_resources": leftovers,
    }
    return stages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--name", required=True, help="Name for the results file")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--test-spec", required=True)
    parser.add_argument("--clone-depth", type=int, default=1)
    parser.add_argument(
        "--deliver", action="store_true",
        help="Pass --confirm-delivery. Without it the run stops before pushing.",
    )
    arguments = parser.parse_args()

    # The run writes its own evidence without passing it through
    # `redacted_document` (apply_run.py:698), so the raw report stays local and
    # git-ignored; only the redacted summary below is committed.
    report_path = RESULTS / "raw" / f"{arguments.name}-run.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "engineering_team.cli", "run-project",
        "--repo", arguments.repo,
        "--clone-depth", str(arguments.clone_depth),
        "--spec", arguments.spec,
        "--test-spec", arguments.test_spec,
        "--authorize-writes",
        "--report-path", str(report_path),
    ]
    if arguments.deliver:
        command.append("--confirm-delivery")

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    evidence: dict = {}
    if report_path.exists():
        evidence = json.loads(report_path.read_text(encoding="utf-8"))

    summary = {
        "repository": arguments.repo,
        "delivered": arguments.deliver,
        "clone_depth": arguments.clone_depth,
        "cli_returncode": completed.returncode,
        "cli_stderr_tail": (completed.stderr or "")[-2000:],
        "stages": _score(evidence, delivered=arguments.deliver),
    }
    summary["all_stages_passed"] = all(
        stage["passed"] for stage in summary["stages"].values()
    )
    destination = RESULTS / f"{arguments.name}.json"
    destination.write_text(
        json.dumps(redacted_document(summary), indent=2), encoding="utf-8"
    )
    for name, stage in summary["stages"].items():
        print(f"{'PASS' if stage['passed'] else 'FAIL'}  {name}")
    return 0 if summary["all_stages_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
