"""One target repository through the whole cycle, scored stage by stage.

A binary pass/fail cannot tell a slow MySQL from an architectural hole. Six
stages are scored independently, so a red one names a place to look.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ASET_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ASET_ROOT / "src"))

from engineering_team.apply_run import target_repo_sha
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ErrorCode, ReviewerStatus, StopCause
from engineering_team.docker_labels import CACHE_LIFETIME, LIFETIME_LABEL, OWNER_FILTER
from engineering_team.guardrails.secrets import redacted_document
from engineering_team.llm.cloud import CloudRouter

RESULTS = Path(__file__).resolve().parent / "results"

# `main()`'s injected default. Named, not `subprocess.run` directly, so a test
# that swaps `run_cycle.subprocess.run` for its own fake (several already do,
# to fake a failing Docker CLI) cannot also change what `main()` calls: the
# default is bound once, at import time, from the real module.
_default_runner = subprocess.run

# Schema version 2 is everything Task 6 adds: `aset_sha`, `specification`,
# `test_specification`, `model_chain`, `started_at`/`finished_at`,
# `target_repo_sha`, `stop_cause`, `environment_failure`, `review_status`, and
# the `stages.clone` rule keyed on `target_repo_sha` instead of `bool(evidence)`.
# An artifact with no `schema_version` key is v1 by convention (see
# `evaluation/benchmarks/README.md`); this scorer never rewrites one.
SCHEMA_VERSION = 2

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


# Named once so the clone stage's `detail` and `evaluation/benchmarks/README.md`
# describe the same rule in the same words, rather than two prose renderings of
# one decision drifting apart.
_CLONE_RULE_V2 = (
    "schema v2 rule: clone passed iff evidence recorded a target_repo_sha"
)


def _clone_stage(evidence: dict) -> dict:
    """Score the clone stage on `target_repo_sha`, not on evidence merely existing.

    `bool(evidence)` (the v1 rule) reads a hang anywhere after a successful
    clone -- mid-execute, mid-delivery -- as a *clone* failure, because by the
    time the run dies there is at least one other key already in the dict and
    the checkout is long gone. `target_repo_sha` is recorded once, read while
    the working copy is still on disk (`apply_run.py:684-722`), and is the one
    fact in the report that can only be true if the checkout happened.

    Absence of the key and an explicit `None` value are not the same claim and
    must not share one `detail`. A missing key means this evidence predates
    Task 5 and the v2 rule has nothing to read -- "not demonstrable under this
    rule", never "clone failed". An explicit `None` means Task 5's own lookup
    ran and came back empty -- "no SHA was obtained". Both score `passed=False`
    (a scorer that cannot demonstrate a pass does not hand out an unearned
    one), but a reader comparing two red clone stages must be able to tell
    "older report" from "this SHA lookup failed" without decoding anything.
    """
    if "target_repo_sha" not in evidence:
        return {
            "passed": False,
            "detail": (
                f"{_CLONE_RULE_V2}; the key is absent, so this evidence predates "
                "Task 5 and cannot be scored by this rule"
            ),
            "target_repo_sha": None,
        }
    sha = evidence["target_repo_sha"]
    if sha is None:
        return {
            "passed": False,
            "detail": f"{_CLONE_RULE_V2}; no SHA was obtained",
            "target_repo_sha": None,
        }
    return {
        "passed": True,
        "detail": f"{_CLONE_RULE_V2}; target_repo_sha={sha}",
        "target_repo_sha": sha,
    }


def _review_status(evidence: dict) -> str:
    """Tri-state the Reviewer's verdict instead of folding "never ran" into a pass or a fail.

    `evidence.get("review")` is `None` both when the run never reached the
    Reviewer and when it exited into human review with no verdict recorded
    (`apply_run.py:795`, `human_review_required=True` alongside `review: null`).
    Neither is an approval and neither is a rejection: B-11 is exactly this
    conflation, so a run that was never judged reads `NOT_EXERCISED`, a
    concept this scorer introduces because the underlying model only has two
    states (`contracts/enums.py:13-15`).
    """
    review = evidence.get("review")
    if not review:
        return "NOT_EXERCISED"
    status = review.get("status")
    if status == ReviewerStatus.APPROVED.value:
        return "APPROVED"
    if status == ReviewerStatus.REJECTED.value:
        return "REJECTED"
    return "NOT_EXERCISED"


def _model_chain(evidence: dict) -> dict[str, dict]:
    """Say what each role actually ran, falling back to what is configured today.

    `evidence["model_usage"]` (`apply_run.py:789`) is what the run exercised:
    entries keyed by `agent` (`contracts/models.py:210-211`), not `role` --
    the same false-friend shape as Task 5's `applied_diff`. Several entries can
    share one `agent` when a fallback retried, in chronological order
    (`graph/stategraph.py:619,622,651,654`); this keeps all of them rather than
    the first or last, since intent is a *chain* of attempts, not one model.

    A role that never appears in `model_usage` never ran, and the only honest
    answer for it is `CloudRouter(Settings()).selection_chain(role)` -- what
    *would* be selected right now, marked `configured` rather than `exercised`
    on purpose. Configuration can change between the run and this count, and
    folding the two together would let a since-edited `.env` masquerade as
    what actually happened during the run being scored.
    """
    usage = evidence.get("model_usage") or []
    exercised: dict[str, list[dict[str, str | None]]] = {}
    for item in usage:
        role = item.get("agent")
        if role is None:
            continue
        exercised.setdefault(role, []).append(
            {"provider": item.get("provider"), "model": item.get("requested_model")}
        )

    router = CloudRouter(Settings())
    chain: dict[str, dict] = {}
    for role in AgentRole:
        entries = exercised.get(role.value)
        if entries:
            chain[role.value] = {"source": "exercised", "chain": entries}
        else:
            configured = router.selection_chain(role)
            chain[role.value] = {
                "source": "configured",
                "chain": [
                    {"provider": selection.provider, "model": selection.model}
                    for selection in configured
                ],
            }
    return chain


def _classify_environment_failure(evidence: dict) -> dict | None:
    """Say whether the *harness* failed, apart from why the run stopped.

    Separate from `stop_cause` on purpose (B-11): a bind-mount that never came
    up is not the same finding as an architectural hole, even when both end
    the run the same way. Three typed signals, none of them a substring match
    on any message:

    1. `stop_cause == StopCause.INFRASTRUCTURE_UNAVAILABLE.value` -- the graph
       itself named this as why the run stopped (`contracts/enums.py:83-91`).
    2. `infrastructure_delivery_error` is present -- ADR 18's delivery step
       raised `DeliveryRefused` and it was recorded (`apply_run.py:562-563`).
    3. Any `tool_outcomes` entry carries
       `error_code == ErrorCode.INFRASTRUCTURE_ERROR.value` -- a tool degraded
       to UNAVAILABLE mid-run even though the run went on to stop for an
       unrelated cause. This reads `error_code`
       (`apply_run.tool_outcomes()`, Ruling 2), never the `errors` list, whose
       entries carry the code as a text prefix (Ruling 3) and are off-limits to
       this phase's no-text-parsing rule.

    Returns `None` when none of the three fired: "no environment failure was
    detected", not "the environment is known good" -- a run whose evidence
    predates `error_code` (before this task) can still slip an infrastructure
    failure past signal 3 with no way for this function to know.
    """
    stop_cause_flagged = (
        evidence.get("stop_cause") == StopCause.INFRASTRUCTURE_UNAVAILABLE.value
    )
    delivery_error = evidence.get("infrastructure_delivery_error")
    tool_outcomes = evidence.get("tool_outcomes") or []
    flagged_tools = [
        item.get("tool")
        for item in tool_outcomes
        if item.get("error_code") == ErrorCode.INFRASTRUCTURE_ERROR.value
    ]
    if not stop_cause_flagged and delivery_error is None and not flagged_tools:
        return None
    return {
        "stop_cause_was_infrastructure_unavailable": stop_cause_flagged,
        "infrastructure_delivery_error": delivery_error,
        "tools_with_infrastructure_error": flagged_tools,
    }


def _score(evidence: dict, *, delivered: bool) -> dict[str, dict]:
    """Read the run's own evidence and say which stages hold.

    Nothing here re-runs anything: the run already answered these questions, and
    a second source of truth is a second thing to keep correct.
    """
    review = evidence.get("review") or {}
    written = evidence.get("files_written") or []
    prerequisite = evidence.get("infrastructure_prerequisite")
    stages: dict[str, dict] = {}

    stages["clone"] = _clone_stage(evidence)
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
    human_review_required = bool(evidence.get("human_review_required"))
    execute_passed = (
        bool(outcomes)
        and not unavailable
        and ran_tests
        and not last_run_tests_failed
        and not human_review_required
    )
    execute_detail = (
        f"{len(outcomes)} tool outcomes, {len(unavailable)} unavailable, "
        f"{len(failed)} failed"
    )
    if human_review_required and not execute_passed:
        execute_detail += ", run exited asking for human review before TESTING closed"
    stages["execute"] = {
        # Tools ran, none degraded, the test tool ran at least once, its last
        # outcome was not FAIL, and the run did not exit into human review: a
        # run whose containers never came up produces an empty list and reads
        # as red, a run that ended on a failing test suite reads as red too,
        # and a run that left the graph via human_review_required can carry a
        # stale PASS from an earlier cycle in run_tests_outcomes[-1] -- that is
        # not a completed TESTING pass, so it must not read as green either.
        "passed": execute_passed,
        "detail": execute_detail,
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


def main(
    argv: list[str] | None = None,
    *,
    runner=_default_runner,
    results_dir: Path = RESULTS,
) -> int:
    """Run the benchmark once and score it.

    `argv`, `runner` and `results_dir` are the minimal injection this task
    adds: a test drives the whole function -- argument parsing, evidence
    loading, scoring, and the write to disk -- without launching a real
    subprocess or touching the operator's actual `results/`. The entry point
    below still calls this with no arguments, so the real CLI is unaffected.
    """
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
    arguments = parser.parse_args(argv)

    # The run writes its own evidence without passing it through
    # `redacted_document` (apply_run.py:698), so the raw report stays local and
    # git-ignored; only the redacted summary below is committed.
    report_path = results_dir / "raw" / f"{arguments.name}-run.json"
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

    started_at = datetime.now(timezone.utc).isoformat()
    completed = runner(command, capture_output=True, text=True, check=False)
    finished_at = datetime.now(timezone.utc).isoformat()
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
        # The ASET commit that produced this run, read from the checkout of
        # ASET itself running the benchmark -- not the target project.
        "aset_sha": target_repo_sha(_ASET_ROOT),
        # The TEXT handed to `--spec`/`--test-spec` (`cli.py:41,63`), not a
        # path: whatever the operator passed on run_cycle.py's own command
        # line travels through to the run being scored.
        "specification": arguments.spec,
        "test_specification": arguments.test_spec,
        "model_chain": _model_chain(evidence),
        "started_at": started_at,
        "finished_at": finished_at,
        # A missing key (evidence older than Task 5) and an explicit `None`
        # ("no SHA was obtained") both surface here as `None`; the distinction
        # that matters is scored in `stages.clone`, not duplicated here.
        "target_repo_sha": evidence.get("target_repo_sha"),
        # Copied verbatim, never reconstructed from error text (Task 3).
        "stop_cause": evidence.get("stop_cause"),
        "environment_failure": _classify_environment_failure(evidence),
        "review_status": _review_status(evidence),
        "stages": _score(evidence, delivered=arguments.deliver),
    }
    # Single point of stamping: every artifact this function writes carries
    # this key, and nothing else in the module sets it.
    summary["schema_version"] = SCHEMA_VERSION
    summary["all_stages_passed"] = all(
        stage["passed"] for stage in summary["stages"].values()
    )
    destination = results_dir / f"{arguments.name}.json"
    destination.write_text(
        json.dumps(redacted_document(summary), indent=2) + "\n", encoding="utf-8"
    )
    for name, stage in summary["stages"].items():
        print(f"{'PASS' if stage['passed'] else 'FAIL'}  {name}")
    return 0 if summary["all_stages_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
