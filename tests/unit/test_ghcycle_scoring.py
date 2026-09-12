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
    monkeypatch.setattr(run_cycle, "_labelled_resources", list)


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
    evidence = {"files_written": ["src/app.py"]}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["clone"]["passed"] is True


def test_clone_is_red_when_there_is_no_evidence_at_all() -> None:
    evidence: dict = {}
    stages = run_cycle._score(evidence, delivered=False)

    assert stages["clone"]["passed"] is False


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
