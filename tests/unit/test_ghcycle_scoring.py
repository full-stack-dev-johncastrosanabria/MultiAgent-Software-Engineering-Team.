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
    evidence: dict = {}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["clone"]["passed"] is False
    assert "target_repo_sha" in stages["clone"]["detail"]
    assert "absent" in stages["clone"]["detail"]


def test_clone_is_red_with_distinct_detail_when_target_repo_sha_is_none() -> None:
    """Absent key ("predates Task 5") and explicit `None` ("no SHA was
    obtained") are different claims about the same evidence and must not
    collapse into one `detail`, per the controller's ruling on this stage."""
    absent = run_cycle._score({}, delivered=False)["clone"]
    none_valued = run_cycle._score({"target_repo_sha": None}, delivered=False)["clone"]

    assert absent["passed"] is False
    assert none_valued["passed"] is False
    assert absent["detail"] != none_valued["detail"]
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
