"""Table tests for `run_cycle._score`.

Tasks 4-6 run this benchmark against spring-demo, PropFlow, and Banking, each
with `--deliver`. Every one of those four runs is scored by this function
alone -- nothing here re-executes anything -- so a mis-scored stage here
means all four reports lie. `_labelled_resources` talks to the Docker daemon,
so it is monkeypatched in every case: the score must not depend on what
happens to be running on the machine that executes the test.

There is no existing precedent under `tests/` for `evaluation/` benchmark
code, so this imports the module by path, same as `run_cycle.py` itself
imports `engineering_team` by inserting `src` onto `sys.path`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import types
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "evaluation" / "benchmarks" / "ghcycle" / "run_cycle.py"
)
_SPEC = importlib.util.spec_from_file_location("run_cycle", _MODULE_PATH)
run_cycle = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(run_cycle)


@pytest.fixture(autouse=True)
def _no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hygiene must not depend on what the local Docker daemon happens to hold."""
    monkeypatch.setattr(run_cycle, "_labelled_resources", lambda: [])


def test_execute_is_red_when_a_tool_went_unavailable() -> None:
    evidence = {
        "tool_outcomes": [
            {"tool": "run_tests", "status": "PASS"},
            {"tool": "static_analysis", "status": "UNAVAILABLE"},
        ],
    }
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["execute"]["passed"] is False


def test_execute_is_red_when_run_tests_never_ran() -> None:
    evidence = {
        "tool_outcomes": [
            {"tool": "static_analysis", "status": "PASS"},
        ],
    }
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["execute"]["passed"] is False


def test_execute_is_red_when_the_terminal_run_tests_iteration_failed() -> None:
    evidence = {
        "tool_outcomes": [
            {"tool": "run_tests", "status": "FAIL"},
            {"tool": "run_tests", "status": "PASS"},
            {"tool": "run_tests", "status": "FAIL"},
        ],
    }
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["execute"]["passed"] is False


def test_execute_is_green_when_the_terminal_run_tests_iteration_passed() -> None:
    evidence = {
        "tool_outcomes": [
            {"tool": "run_tests", "status": "FAIL"},
            {"tool": "run_tests", "status": "PASS"},
        ],
    }
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["execute"]["passed"] is True


def test_execute_is_red_when_the_run_exited_into_human_review_despite_a_stale_pass() -> None:
    """The real case seen in all three raw reports: the graph left via
    `human_review_required` before TESTING closed, but `run_tests_outcomes[-1]`
    still carries a PASS from an earlier cycle. That PASS is not a completed
    TESTING pass for *this* run, so `execute` must not read green on it."""
    evidence = {
        "tool_outcomes": [
            {"tool": "run_tests", "status": "PASS"},
        ],
        "human_review_required": True,
        "review": {"status": "REJECTED"},
    }
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["execute"]["passed"] is False
    assert "human review" in stages["execute"]["detail"]


def test_execute_is_green_when_the_terminal_run_tests_passed_and_no_human_review() -> None:
    evidence = {
        "tool_outcomes": [
            {"tool": "run_tests", "status": "PASS"},
        ],
        "human_review_required": False,
    }
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["execute"]["passed"] is True


def test_spec_is_red_when_files_were_written_but_the_reviewer_rejected() -> None:
    evidence = {
        "files_written": ["src/app.py"],
        "review": {"status": "REJECTED"},
    }
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["spec"]["passed"] is False


def test_delivery_is_red_when_delivered_but_no_pr_url() -> None:
    # `delivered` is a keyword argument to `_score`, not an evidence key: `_score`
    # never reads `evidence["delivered"]`, so it does not belong in this dict.
    evidence: dict = {}
    stages = run_cycle._score(evidence, delivered=True)

    assert stages["delivery"]["passed"] is False


def test_infrastructure_is_red_when_prerequisite_present_and_delivered_without_branch() -> None:
    evidence = {
        "infrastructure_prerequisite": {"docker_compose": True},
        "infrastructure_branch": None,
    }
    stages = run_cycle._score(evidence, delivered=True)

    assert stages["infrastructure"]["passed"] is False


def test_clone_is_green_when_the_run_produced_any_evidence() -> None:
    # T6, schema v2: clone now depends on `target_repo_sha`, not on evidence
    # merely existing -- a hang after a successful clone must not read as a
    # clone failure. The consejo-de-cuatro-voces ruling changes this test's
    # semantics rather than adding a parallel stage; the fixture below gains
    # the key that makes the new rule true.
    evidence = {"files_written": ["src/app.py"], "target_repo_sha": "deadbeef"}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["clone"]["passed"] is True


def test_clone_is_red_when_there_is_no_evidence_at_all() -> None:
    """`main()` folds "the run wrote no report" and "the report could not be
    parsed" into `{}` alike (fix round 1, Important 1): this is the common
    case for a run that crashed, hung, or was killed before it could persist
    anything, and it says nothing about whether the clone itself succeeded --
    it must not be reported as "this evidence predates Task 5", which is a
    claim about an old but *present* report, not a claim about a missing one.
    """
    evidence: dict = {}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["clone"]["passed"] is False
    assert "wrote no report" in stages["clone"]["detail"]
    assert "predates Task 5" not in stages["clone"]["detail"]


def test_clone_is_red_with_predates_task_5_detail_when_a_real_report_lacks_the_key() -> None:
    """A *non-empty* report missing `target_repo_sha` is a different claim
    from no report at all: it means a real, older CLI wrote this evidence
    before Task 5 added the field, not that the run produced nothing."""
    evidence = {"files_written": ["src/app.py"]}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["clone"]["passed"] is False
    assert "predates Task 5" in stages["clone"]["detail"]


def test_clone_is_red_with_distinct_detail_when_target_repo_sha_is_none() -> None:
    """No report, a real report predating Task 5, and a current report with
    an explicit `None` are three different claims about the evidence and must
    not collapse into shared `detail` text, per the controller's ruling on
    this stage."""
    no_report = run_cycle._score({}, delivered=False)["clone"]
    predates_t5 = run_cycle._score({"files_written": ["x"]}, delivered=False)["clone"]
    none_valued = run_cycle._score({"target_repo_sha": None}, delivered=False)["clone"]

    assert no_report["passed"] is False
    assert predates_t5["passed"] is False
    assert none_valued["passed"] is False
    details = {no_report["detail"], predates_t5["detail"], none_valued["detail"]}
    assert len(details) == 3
    assert "no sha was obtained" in none_valued["detail"].lower()


def test_review_status_is_approved() -> None:
    evidence = {"review": {"status": "APPROVED"}}

    assert run_cycle._review_status(evidence) == "APPROVED"


def test_review_status_is_rejected() -> None:
    evidence = {"review": {"status": "REJECTED"}}

    assert run_cycle._review_status(evidence) == "REJECTED"


def test_review_status_is_not_exercised_when_review_never_ran() -> None:
    # Covers both shapes B-11 conflates with a verdict: the key entirely
    # absent, and `human_review_required=True` alongside `review: null`
    # (apply_run.py:795) -- neither is an approval and neither is a rejection.
    assert run_cycle._review_status({}) == "NOT_EXERCISED"
    assert run_cycle._review_status({"review": None}) == "NOT_EXERCISED"
    assert (
        run_cycle._review_status({"human_review_required": True, "review": None})
        == "NOT_EXERCISED"
    )


def test_model_chain_marks_exercised_role_from_model_usage() -> None:
    # The role key is `agent`, not `role` (contracts/models.py:210-211) --
    # the same false-friend shape the brief warns Task 6 about.
    evidence = {
        "model_usage": [
            {"agent": "Developer", "provider": "openai", "requested_model": "gpt-oss-120b"},
        ],
    }
    chain = run_cycle._model_chain(evidence)

    assert chain["Developer"] == {
        "source": "exercised",
        "chain": [{"provider": "openai", "model": "gpt-oss-120b"}],
    }


def test_model_chain_falls_back_to_configured_for_role_never_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role absent from `model_usage` never ran; the only honest answer is
    what `CloudRouter.selection_chain` would pick today, marked `configured`
    rather than `exercised` because configuration can drift from what a past
    run actually did. `selection_chain` returns `ModelSelection` dataclasses
    in production (`llm/registry.py:8-13`) -- the fake below is a plain
    attribute-bearing double, not that class, to prove the composing code only
    relies on `.provider`/`.model` and not on the concrete dataclass type.
    """

    def _fake_selection_chain(self, role):
        return (types.SimpleNamespace(provider="fake-provider", model="fake-model"),)

    monkeypatch.setattr(run_cycle.CloudRouter, "selection_chain", _fake_selection_chain)

    chain = run_cycle._model_chain({"model_usage": []})

    assert chain["Product"] == {
        "source": "configured",
        "chain": [{"provider": "fake-provider", "model": "fake-model"}],
    }


def test_classify_environment_failure_flags_infrastructure_unavailable_and_none_otherwise() -> None:
    flagged = run_cycle._classify_environment_failure({"stop_cause": "infrastructure_unavailable"})
    clean = run_cycle._classify_environment_failure({"stop_cause": "approved"})

    assert flagged is not None
    assert clean is None


def test_classify_environment_failure_flags_a_tool_level_infrastructure_error_even_when_stop_cause_is_unrelated() -> None:
    """Ruling 2's `error_code` on `tool_outcomes` exists exactly for this: a
    run that hit an infrastructure blip mid-run but went on to stop for an
    unrelated reason (here, the iteration limit) must still surface the
    environment failure -- B-11 says a bind-mount failure is not the same
    finding as a run that simply ran out of iterations."""
    evidence = {
        "stop_cause": "iteration_limit",
        "tool_outcomes": [
            {"tool": "run_tests", "status": "UNAVAILABLE", "error_code": "INFRASTRUCTURE_ERROR"},
        ],
    }
    result = run_cycle._classify_environment_failure(evidence)

    assert result is not None
    assert "run_tests" in result["tools_with_infrastructure_error"]


def test_main_stamps_schema_version_2_via_injected_runner_and_results_dir(tmp_path) -> None:
    def _fake_runner(command, **kwargs):
        report_path = Path(command[command.index("--report-path") + 1])
        report_path.write_text(
            json.dumps({"target_repo_sha": "deadbeef", "model_usage": [], "review": None}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    exit_code = run_cycle.main(
        [
            "--repo", "https://example.test/r.git", "--name", "demo",
            "--spec", "spec text", "--test-spec", "test spec text",
        ],
        runner=_fake_runner,
        results_dir=tmp_path,
    )

    written = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert written["schema_version"] == 2
    assert exit_code in (0, 1)


def test_main_does_not_write_to_the_real_results_directory(tmp_path) -> None:
    """The injected `results_dir` must be the only place `main()` writes to --
    otherwise every other test in this module risks polluting the operator's
    real `evaluation/benchmarks/ghcycle/results/`."""
    name = "__t6_injection_guard__"
    real_summary = run_cycle.RESULTS / f"{name}.json"
    real_raw = run_cycle.RESULTS / "raw" / f"{name}-run.json"
    assert not real_summary.exists()
    assert not real_raw.exists()

    def _fake_runner(command, **kwargs):
        report_path = Path(command[command.index("--report-path") + 1])
        report_path.write_text(
            json.dumps({"target_repo_sha": "cafebabe"}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    try:
        run_cycle.main(
            [
                "--repo", "https://example.test/r.git", "--name", name,
                "--spec", "x", "--test-spec", "y",
            ],
            runner=_fake_runner,
            results_dir=tmp_path,
        )
        assert not real_summary.exists()
        assert not real_raw.exists()
        assert (tmp_path / f"{name}.json").exists()
    finally:
        real_summary.unlink(missing_ok=True)
        real_raw.unlink(missing_ok=True)


def test_main_pins_pythonpath_to_aset_root_for_the_runner(tmp_path) -> None:
    """Fix round 1, Important 3: without pinning `PYTHONPATH`, the subprocess
    resolves `engineering_team` however the shared `.venv`'s own editable
    install points, which, run from a worktree, is the main checkout's `src`
    -- not the one `aset_sha` names. `main()` must hand the runner an `env`
    that pins the subprocess to import from `_ASET_ROOT` itself."""
    captured_kwargs: dict = {}

    def _fake_runner(command, **kwargs):
        captured_kwargs.update(kwargs)
        report_path = Path(command[command.index("--report-path") + 1])
        report_path.write_text(
            json.dumps({"target_repo_sha": "deadbeef"}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    run_cycle.main(
        [
            "--repo", "https://example.test/r.git", "--name", "envtest",
            "--spec", "x", "--test-spec", "y",
        ],
        runner=_fake_runner,
        results_dir=tmp_path,
    )

    assert captured_kwargs["env"]["PYTHONPATH"] == str(run_cycle._ASET_ROOT / "src")


def test_aset_dirty_is_true_when_git_status_reports_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_cycle.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=" M some/file.py\n", stderr=""),
    )

    assert run_cycle._aset_dirty() is True


def test_aset_dirty_is_false_when_git_status_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_cycle.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="", stderr=""),
    )

    assert run_cycle._aset_dirty() is False


def test_aset_dirty_is_none_when_git_cannot_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers both ways the question can go unanswered: git raising (missing
    binary, not a repository under some git versions) and git exiting
    non-zero. Neither may read as `False` ("clean"): a failed check must not
    be reported as a known-good result."""

    def _raise(*_a: object, **_kw: object) -> None:
        raise OSError("git: command not found")

    monkeypatch.setattr(run_cycle.subprocess, "run", _raise)
    assert run_cycle._aset_dirty() is None

    monkeypatch.setattr(
        run_cycle.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 128, stdout="", stderr="not a git repository"),
    )
    assert run_cycle._aset_dirty() is None


def test_hygiene_is_green_when_nothing_is_labelled() -> None:
    evidence: dict = {}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["hygiene"]["passed"] is True


def test_hygiene_is_red_when_the_daemon_could_not_be_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same rule as `execute`: a question the benchmark could not answer is not a PASS."""

    def _unreachable() -> list[str]:
        raise run_cycle.DockerQueryFailed("docker images --quiet: [Errno 2] No such file")

    monkeypatch.setattr(run_cycle, "_labelled_resources", _unreachable)
    evidence: dict = {}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["hygiene"]["passed"] is False
    assert "docker images" in stages["hygiene"]["detail"]


def test_listed_raises_docker_query_failed_when_the_subprocess_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("docker: command not found")

    monkeypatch.setattr(run_cycle.subprocess, "run", _raise)

    with pytest.raises(run_cycle.DockerQueryFailed):
        run_cycle._listed(["docker", "ps", "-a", "--format", "{{.Names}}"])


def test_listed_raises_docker_query_failed_on_nonzero_returncode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "Cannot connect to the Docker daemon"

    monkeypatch.setattr(
        run_cycle.subprocess, "run", lambda *_a, **_kw: _FakeCompleted()
    )

    with pytest.raises(run_cycle.DockerQueryFailed):
        run_cycle._listed(["docker", "ps", "-a", "--format", "{{.Names}}"])


# -- I-1 / m-7: the ASET checkout is read before the run, and again after ----


def _main_with(tmp_path, runner, name="demo", *extra):
    """Drive `main()` end to end and read back the artifact it actually wrote."""
    exit_code = run_cycle.main(
        [
            "--repo", "https://example.test/r.git", "--name", name,
            "--spec", "spec text", "--test-spec", "test spec text", *extra,
        ],
        runner=runner,
        results_dir=tmp_path,
    )
    return exit_code, json.loads((tmp_path / f"{name}.json").read_text(encoding="utf-8"))


def _writes_report(evidence: dict, returncode: int = 0):
    def _fake_runner(command, **kwargs):
        report_path = Path(command[command.index("--report-path") + 1])
        report_path.write_text(json.dumps(evidence), encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr="")

    return _fake_runner


def test_main_records_the_aset_checkout_as_it_was_before_the_run(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I-1: a commit, amend or branch switch while the run is in flight must not
    let the artifact certify code that did not run. The fake runner is the
    operator committing mid-run: both readings change between the two reads."""
    moved = {"on": False}
    monkeypatch.setattr(
        run_cycle, "target_repo_sha", lambda _root: "after" if moved["on"] else "before"
    )
    monkeypatch.setattr(run_cycle, "_aset_dirty", lambda: moved["on"])
    report = _writes_report({"target_repo_sha": "deadbeef"})

    def _operator_commits_mid_run(command, **kwargs):
        moved["on"] = True
        return report(command, **kwargs)

    _, written = _main_with(tmp_path, _operator_commits_mid_run)

    assert written["aset_sha"] == "before"
    assert written["aset_dirty"] is False
    assert written["aset_changed_during_run"] is True


def test_main_says_the_checkout_held_still_when_it_did(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_cycle, "target_repo_sha", lambda _root: "same")
    monkeypatch.setattr(run_cycle, "_aset_dirty", lambda: False)

    _, written = _main_with(tmp_path, _writes_report({"target_repo_sha": "deadbeef"}))

    assert written["aset_sha"] == "same"
    assert written["aset_changed_during_run"] is False


def test_main_cannot_vouch_for_a_checkout_it_could_not_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`None` is "could not tell", never "unchanged"; a difference it *can* see
    is still a change."""
    monkeypatch.setattr(run_cycle, "target_repo_sha", lambda _root: "same")
    monkeypatch.setattr(run_cycle, "_aset_dirty", lambda: None)

    _, written = _main_with(tmp_path, _writes_report({"target_repo_sha": "deadbeef"}))

    assert written["aset_changed_during_run"] is None


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.test",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *arguments],
        check=True, capture_output=True, text=True,
    )


def test_aset_dirty_sees_a_new_untracked_module_under_src(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m-7, against a real repository: a new module under `src/` runs whether
    or not it was ever `git add`-ed, so a tree carrying one is not the commit
    `aset_sha` names. Untracked output elsewhere (this benchmark's own
    `results/*.json`) and ignored files under `src/` stay ordinary use."""
    repo = tmp_path / "aset"
    (repo / "src" / "engineering_team").mkdir(parents=True)
    (repo / "src" / "engineering_team" / "existing.py").write_text("x = 1\n")
    (repo / ".gitignore").write_text("__pycache__/\n")
    _git(repo, "init", "--quiet")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "base")
    monkeypatch.setattr(run_cycle, "_ASET_ROOT", repo)

    assert run_cycle._aset_dirty() is False

    (repo / "results").mkdir()
    (repo / "results" / "run.json").write_text("{}")
    (repo / "src" / "engineering_team" / "__pycache__").mkdir()
    (repo / "src" / "engineering_team" / "__pycache__" / "existing.pyc").write_bytes(b"")
    assert run_cycle._aset_dirty() is False

    (repo / "src" / "engineering_team" / "new_module.py").write_text("y = 2\n")
    assert run_cycle._aset_dirty() is True


# -- I-3: a typed failure before the graph crosses the process boundary -------


def _no_report(returncode: int):
    def _fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command, returncode, stdout="", stderr="Traceback (most recent call last): ..."
        )

    return _fake_runner


def test_main_maps_the_cli_infrastructure_exit_to_both_typed_fields(tmp_path) -> None:
    from engineering_team.contracts.enums import INFRASTRUCTURE_EXIT_CODE

    exit_code, written = _main_with(tmp_path, _no_report(INFRASTRUCTURE_EXIT_CODE))

    assert written["cli_returncode"] == INFRASTRUCTURE_EXIT_CODE
    assert written["stop_cause"] == "infrastructure_unavailable"
    assert written["environment_failure"] is not None
    assert written["environment_failure"]["cli_exited_infrastructure_unavailable"] is True
    assert exit_code == 1


def test_main_names_any_other_nonzero_exit_without_a_report_a_crash(tmp_path) -> None:
    """`StopCause.CRASH` exists for exactly this, and an ASET crash is not an
    environment failure."""
    _, written = _main_with(tmp_path, _no_report(1))

    assert written["stop_cause"] == "crash"
    assert written["environment_failure"] is None


def test_main_reads_the_reports_own_stop_cause_whenever_there_is_a_report(tmp_path) -> None:
    """The exit status only speaks when the report cannot."""
    from engineering_team.contracts.enums import INFRASTRUCTURE_EXIT_CODE

    _, written = _main_with(tmp_path, _writes_report(
        {"target_repo_sha": "deadbeef", "stop_cause": "iteration_limit"},
        returncode=INFRASTRUCTURE_EXIT_CODE,
    ))

    assert written["stop_cause"] == "iteration_limit"
    assert written["environment_failure"] is None


# -- I-4: a dry run does not score unexercised stages as passed -------------------


_PREREQUISITE = {"engines": ["mysql"], "read_from": ["src/main/resources/application.yaml"]}


def test_a_dry_run_does_not_score_delivery_or_an_undelivered_prerequisite_as_passed() -> None:
    """The "corrida en seco" test the spec row asks for (S1/S2, "21/26
    aprobados vacíos"): nothing was pushed, so neither stage was exercised,
    and a stage that was never exercised is neither a pass nor a fail."""
    stages = run_cycle._score(
        {"target_repo_sha": "deadbeef", "infrastructure_prerequisite": _PREREQUISITE},
        delivered=False,
    )

    assert stages["delivery"]["exercised"] is False
    assert stages["delivery"]["passed"] is None
    assert stages["infrastructure"]["exercised"] is False
    assert stages["infrastructure"]["passed"] is None


def test_a_dry_run_with_nothing_to_deliver_passes_infrastructure_legitimately() -> None:
    """A recorded `None` prerequisite is an answer: the project needed nothing."""
    stages = run_cycle._score(
        {"target_repo_sha": "deadbeef", "infrastructure_prerequisite": None},
        delivered=False,
    )

    assert stages["infrastructure"]["exercised"] is True
    assert stages["infrastructure"]["passed"] is True


def test_a_run_that_wrote_no_report_never_answered_the_infrastructure_question() -> None:
    """Absent is not `None`: with no report the prerequisite was never
    determined, the same distinction the clone stage draws for its SHA."""
    stages = run_cycle._score({}, delivered=False)

    assert stages["infrastructure"]["exercised"] is False
    assert stages["infrastructure"]["passed"] is None


def test_every_stage_says_whether_it_was_exercised() -> None:
    stages = run_cycle._score(
        {"target_repo_sha": "deadbeef", "infrastructure_prerequisite": _PREREQUISITE},
        delivered=True,
    )

    assert set(stages) == {"clone", "infrastructure", "execute", "spec", "delivery", "hygiene"}
    assert all(stage["exercised"] is True for stage in stages.values())
    assert all(isinstance(stage["passed"], bool) for stage in stages.values())


_GREEN_DRY_RUN = {
    "target_repo_sha": "deadbeef",
    "infrastructure_prerequisite": _PREREQUISITE,
    "tool_outcomes": [{"tool": "run_tests", "status": "PASS", "error_code": None}],
    "files_written": ["src/app.py"],
    "review": {"status": "APPROVED"},
    "human_review_required": False,
    "stop_cause": "approved",
}


def test_main_on_a_green_dry_run_exits_zero_without_claiming_every_stage_passed(
    tmp_path, capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, written = _main_with(tmp_path, _writes_report(_GREEN_DRY_RUN))

    assert exit_code == 0
    assert written["all_stages_passed"] is False
    assert written["all_exercised_stages_passed"] is True
    assert written["stages_not_exercised"] == ["infrastructure", "delivery"]
    assert written["stages"]["delivery"]["passed"] is None
    assert written["stages"]["infrastructure"]["passed"] is None
    printed = capsys.readouterr().out.splitlines()
    for name in ("infrastructure", "delivery"):
        line = next(item for item in printed if item.split()[1] == name)
        assert not line.startswith(("PASS", "FAIL"))
        assert "not exercised" in line


def test_main_on_a_red_dry_run_still_exits_nonzero(tmp_path) -> None:
    rejected = {**_GREEN_DRY_RUN, "review": {"status": "REJECTED"}}

    exit_code, written = _main_with(tmp_path, _writes_report(rejected))

    assert exit_code == 1
    assert written["all_exercised_stages_passed"] is False
    assert written["all_stages_passed"] is False


def test_main_on_a_green_delivered_run_passes_every_stage(tmp_path) -> None:
    delivered = {
        **_GREEN_DRY_RUN,
        "infrastructure_branch": "aset/infra-1",
        "delivery_pr_url": "https://example.test/pr/1",
    }

    exit_code, written = _main_with(tmp_path, _writes_report(delivered), "demo", "--deliver")

    assert exit_code == 0
    assert written["all_stages_passed"] is True
    assert written["all_exercised_stages_passed"] is True
    assert written["stages_not_exercised"] == []
