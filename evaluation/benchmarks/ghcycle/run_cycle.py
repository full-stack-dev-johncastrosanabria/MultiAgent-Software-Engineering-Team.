"""One target repository through the whole cycle, scored stage by stage.

A binary pass/fail cannot tell a slow MySQL from an architectural hole. Six
stages are scored independently, so a red one names a place to look.
"""

import argparse
import json
import os
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

# Schema version 2 is everything Task 6 adds: `aset_sha`, `aset_dirty`,
# `specification`, `test_specification`, `model_chain`, `started_at`/
# `finished_at`, `target_repo_sha`, `stop_cause`, `environment_failure`,
# `review_status`, and the `stages.clone` rule that additionally requires
# `target_repo_sha` on top of a report having been written at all. An
# artifact with no `schema_version` key is v1 by convention (see
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


_GIT_STATUS_TIMEOUT_SECONDS = 10


def _aset_dirty() -> bool | None:
    """Whether the ASET checkout that is about to run has uncommitted changes.

    `aset_sha` names a commit; this says whether the working tree matched it.
    A clean SHA next to a dirty tree would let a run be attributed to code
    that was never actually committed. Untracked files are excluded on
    purpose (`--untracked-files=no`): this same checkout accumulates its own
    git-ignored output while the benchmark runs (`results/raw/`, the shared
    `.venv`), and counting those would flag ordinary use of this benchmark as
    a modified harness.

    `None` means the question itself could not be answered -- git is
    missing, `_ASET_ROOT` is not a repository, or the command exits non-zero
    or times out -- and is deliberately distinct from `False` ("asked, and
    the tree is clean"): a failed check must not read as a clean result.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(_ASET_ROOT), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True,
            timeout=_GIT_STATUS_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip())


# Named once so the clone stage's `detail` and `evaluation/benchmarks/README.md`
# describe the same rule in the same words, rather than two prose renderings of
# one decision drifting apart.
_CLONE_RULE_V2 = (
    "schema v2 rule: clone passed iff evidence recorded a target_repo_sha"
)


def _clone_stage(evidence: dict) -> dict:
    """Score the clone stage on `target_repo_sha`, not on evidence merely existing.

    The real difference between the two rules is this: v1 asked only "was a
    report written" (`bool(evidence)`); v2 asks "was a report written *and*
    did it record a target SHA". v2 can therefore only turn a v1 pass into a
    fail -- a report that exists but carries no `target_repo_sha` -- never
    the reverse, because a report that satisfies v2 always satisfies v1 too.

    This does not fix the case the brief named (a hang after a successful
    clone reading as a clone failure): the CLI persists its report only once,
    at the very end of a completed run (`apply_run.py:900-903`), so a run
    that dies partway through leaves no report under v1 *or* v2, and neither
    rule can distinguish a died-after-clone run from a died-before-clone run.
    What v2 adds is a name for that case -- see the `not evidence` branch
    below -- not a fix for it; fixing it would mean the CLI persisting clone
    evidence before it can die, which changes Task 5's report contract and is
    out of this task's scope.

    Three distinct claims about the evidence, three distinct `detail`s, all
    `passed=False` except the last (a scorer that cannot demonstrate a pass
    does not hand out an unearned one):

    1. `not evidence` -- no report exists to read at all: the run wrote none,
       or what it wrote could not be parsed (`main()` folds both into `{}`).
       This is the common case for a run that crashed, hung, or was killed;
       it says nothing about whether the clone itself succeeded.
    2. `evidence` is non-empty but lacks `target_repo_sha` -- a report was
       written by a CLI old enough to predate Task 5, so the v2 rule has
       nothing to read.
    3. `evidence["target_repo_sha"] is None` -- a current CLI wrote the
       report and Task 5's own lookup ran, but came back empty.

    A reader comparing two red clone stages must be able to tell these three
    apart without decoding anything.
    """
    if not evidence:
        return {
            "passed": False,
            "detail": (
                f"{_CLONE_RULE_V2}; the run wrote no report (or it could not "
                "be parsed), so the clone cannot be demonstrated from "
                "evidence -- this does not mean the clone failed"
            ),
            "target_repo_sha": None,
        }
    if "target_repo_sha" not in evidence:
        return {
            "passed": False,
            "detail": (
                f"{_CLONE_RULE_V2}; a report exists but the key is absent, so "
                "this evidence predates Task 5 and cannot be scored by this "
                "rule"
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
    """Say whether the *environment* failed, apart from why the run stopped.

    Not "the harness" -- ASET is the harness, and a bind-mount failure is not
    a failure of ASET (B-11); it is a failure of the infrastructure ASET
    depends on to run at all. Separate from `stop_cause` on purpose: a
    bind-mount that never came up is not the same finding as an architectural
    hole, even when both end the run the same way. Three typed signals, none
    of them a substring match on any message:

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
    # `aset_sha` below names the commit at `_ASET_ROOT`. Without pinning
    # `PYTHONPATH`, the subprocess resolves `engineering_team` however the
    # shared `.venv`'s own editable install points -- which, run from a
    # worktree, is the *main checkout's* `src`, not this one's. Pinning it
    # here is what makes `aset_sha` name the code that actually executed.
    completed = runner(
        command, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": str(_ASET_ROOT / "src")},
    )
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
        # ASET itself running the benchmark -- not the target project. The
        # subprocess above is pinned to import from this same checkout via
        # `PYTHONPATH`, so this SHA names the code that actually ran.
        "aset_sha": target_repo_sha(_ASET_ROOT),
        # Whether that checkout had uncommitted changes when the run started.
        # `None` means the check itself could not be answered, not "clean".
        "aset_dirty": _aset_dirty(),
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
