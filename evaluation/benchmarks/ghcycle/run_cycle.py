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

from engineering_team.docker_labels import CACHE_LIFETIME, LIFETIME_LABEL, OWNER_FILTER
from engineering_team.guardrails.secrets import redacted_document

RESULTS = Path(__file__).resolve().parent / "results"

_DOCKER_TIMEOUT_SECONDS = 30


# ADR 16 labels containers, named volumes and networks alike, and its own
# inventory measured volumes as the bulk of the leak. Asking only about
# containers would read green with a stale volume still standing.
_RESOURCE_QUERIES = (
    ("container", ["docker", "ps", "-a", "--format", "{{.Names}}"]),
    ("volume", ["docker", "volume", "ls", "--format", "{{.Name}}"]),
    ("network", ["docker", "network", "ls", "--format", "{{.Name}}"]),
)
_IMAGE_QUERY = ["docker", "images", "--quiet"]
_OWNER_LABEL_FILTER = f"label={OWNER_FILTER}"
_CACHE_LABEL_FILTER = f"label={LIFETIME_LABEL}={CACHE_LIFETIME}"


class DockerQueryFailed(RuntimeError):
    """The daemon could not be asked, which is distinct from it answering nothing."""


def _listed(query: list[str], *filters: str) -> set[str]:
    arguments = list(query)
    for expression in filters:
        arguments += ["--filter", expression]
    try:
        completed = subprocess.run(
            arguments, capture_output=True, text=True,
            timeout=_DOCKER_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DockerQueryFailed(f"{' '.join(arguments)}: {exc}") from exc
    if completed.returncode != 0:
        raise DockerQueryFailed(
            f"{' '.join(arguments)} exited {completed.returncode}: "
            f"{completed.stderr.strip()[-200:]}"
        )
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def _labelled_resources() -> list[str]:
    """Name every resource ASET labelled as its own, across resource kinds.

    The filter is `aset.owner=aset` everywhere: a resource nobody labelled is
    never reported, so an unrelated container on the machine stays invisible.

    Images get the same owner filter plus the `aset.lifetime=cache` exclusion
    `docker_labels.sweep` applies before reaping -- a pulled base image, a
    package cache -- deliberately persistent so a later run can reuse it, and
    counting it as a leftover would leave this stage red forever. Unlike
    `sweep`, this does not also exclude the current run's own `aset.run`:
    hygiene is measured *after* the run finishes, so its own leftovers are
    exactly what this is looking for.

    Queried by id (`--quiet`), not by name: an untagged image reports as
    `<none>:<none>` under `{{.Repository}}:{{.Tag}}`, so a single untagged
    `cache` image would have made the set-difference below swallow any
    untagged `run` leftover too -- a false green in the one stage whose whole
    job is catching leftovers.

    Raises `DockerQueryFailed` if any query could not be answered -- the
    daemon is unreachable, absent, or exits non-zero. Distinguishing "asked
    and got nothing" from "could not ask" is deliberate: `docker_labels.sweep`
    returns `set()` on the same failure and that is correct there, because in
    a sweep "don't know" must mean "delete nothing" -- fail closed. Here the
    same `set()` would mean "declare clean" -- fail open, and hygiene is a
    stage this benchmark scores, not a best-effort cleanup.
    """
    found: list[str] = []
    for kind, query in _RESOURCE_QUERIES:
        found.extend(
            f"{kind}/{name}" for name in sorted(_listed(query, _OWNER_LABEL_FILTER))
        )
    owned_images = _listed(_IMAGE_QUERY, _OWNER_LABEL_FILTER)
    cached_images = _listed(_IMAGE_QUERY, _OWNER_LABEL_FILTER, _CACHE_LABEL_FILTER)
    found.extend(f"image/{name}" for name in sorted(owned_images - cached_images))
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
    run_tests_outcomes = [item for item in outcomes if item.get("tool") == "run_tests"]
    ran_tests = bool(run_tests_outcomes)
    # An intermediate FAIL does not turn the stage red: a TDD loop is meant to
    # go red before it goes green, so failures are normal mid-run. They are
    # counted anyway, because a run whose tests failed every iteration but the
    # last should still show that history. But the *last* run_tests outcome is
    # different: if the loop never got back to green, the run shipped whatever
    # it had -- observed once as 0 files written -- and that is not a stage
    # this benchmark can call PASS.
    last_run_tests_failed = ran_tests and run_tests_outcomes[-1].get("status") == "FAIL"
    failed = [item for item in outcomes if item.get("status") == "FAIL"]
    failed_by_tool = {
        tool: sum(1 for item in failed if item.get("tool") == tool)
        for tool in sorted({item.get("tool") for item in failed})
    }
    stages["execute"] = {
        # Tools ran, none degraded, the test tool ran at least once, and its
        # last outcome was not FAIL: a run whose containers never came up
        # produces an empty list and reads as red, and a run that ended on a
        # failing test suite reads as red too.
        "passed": bool(outcomes) and not unavailable and ran_tests and not last_run_tests_failed,
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
    try:
        leftovers = _labelled_resources()
    except DockerQueryFailed as exc:
        # The daemon could not be asked, so this stage did not measure a clean
        # state -- it measured nothing. Same rule as `execute`: the benchmark
        # does not hand out PASS for a question it could not answer.
        stages["hygiene"] = {"passed": False, "detail": str(exc)}
    else:
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
    # A crash before the CLI writes its report must not leave a stale report
    # from a previous run sitting there to be scored as if it were this one.
    report_path.unlink(missing_ok=True)
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
        try:
            evidence = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # A crash mid-write leaves a truncated file; treat it the same as
            # no report at all rather than raising out of the benchmark.
            evidence = {}

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
        json.dumps(redacted_document(summary), indent=2) + "\n", encoding="utf-8"
    )
    for name, stage in summary["stages"].items():
        print(f"{'PASS' if stage['passed'] else 'FAIL'}  {name}")
    return 0 if summary["all_stages_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
