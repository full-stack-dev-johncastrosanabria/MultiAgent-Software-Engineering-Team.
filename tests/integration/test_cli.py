import subprocess

from typer.testing import CliRunner

from engineering_team import cli
from engineering_team.contracts.enums import INFRASTRUCTURE_EXIT_CODE, ErrorCode


def test_cli_accepts_requirement_and_reports_run_evidence(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(settings, *, requirement, report_path):
        captured.update(requirement=requirement, report_path=report_path)
        return {"run_id": "run-1", "trace_id": "trace-1", "final_status": "APPROVED"}

    monkeypatch.setattr(cli, "run_multimodel_acceptance", fake_run)
    result = CliRunner().invoke(
        cli.app, ["run", "password recovery", "--report-path", str(tmp_path / "run.json")]
    )

    assert result.exit_code == 0
    assert '"final_status": "APPROVED"' in result.stdout
    assert captured["requirement"] == "password recovery"


def test_docker_sweep_reports_and_exits_nonzero_when_the_runtime_never_answered(
    monkeypatch,
) -> None:
    """The same typed refusal apply_run.py:217 makes for the entry-point sweep
    (A-13/B-11): an unresponsive runtime is not a clean sweep the operator
    should read as exit 0, and --build-cache must not run afterwards."""
    prune_calls: list[list[str]] = []

    def fake_sweep(*args, **kwargs):
        return {
            "containers": ["dead"], "networks": [], "volumes": [], "images": [],
            "error_code": ErrorCode.INFRASTRUCTURE_ERROR,
        }

    def fake_subprocess_run(argv, **kwargs):
        prune_calls.append(argv)
        raise AssertionError("docker builder prune must not run after an unresponsive sweep")

    monkeypatch.setattr(cli, "sweep", fake_sweep)
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    result = CliRunner().invoke(cli.app, ["docker-sweep", "--build-cache"])

    assert result.exit_code == INFRASTRUCTURE_EXIT_CODE
    assert prune_calls == []
    assert '"error_code": "INFRASTRUCTURE_ERROR"' in result.stdout
    # The partial report still reaches the operator -- it is not thrown away.
    assert '"dead"' in result.stdout


def test_docker_sweep_exits_zero_and_prunes_when_the_sweep_actually_ran(
    monkeypatch,
) -> None:
    def fake_sweep(*args, **kwargs):
        return {
            "containers": [], "networks": [], "volumes": [], "images": [],
            "error_code": None,
        }

    class _Completed:
        stdout = "Total reclaimed space: 0B\n"

    monkeypatch.setattr(cli, "sweep", fake_sweep)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Completed())

    result = CliRunner().invoke(cli.app, ["docker-sweep", "--build-cache"])

    assert result.exit_code == 0
    assert '"error_code": null' in result.stdout
    assert '"build_cache"' in result.stdout


def test_docker_sweep_exits_nonzero_when_the_daemon_refuses_to_list(monkeypatch) -> None:
    """Deferred L1069, end to end through the real `sweep`: a stopped daemon or a
    denied socket makes `docker ps` exit 1 at once. That used to print an
    all-empty report with `error_code: null` and exit 0 -- "nothing to clean"
    from a sweep that never looked."""
    from engineering_team import docker_labels

    monkeypatch.setattr(docker_labels.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_labels.subprocess, "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 1, "", "permission denied while trying to connect to the Docker daemon socket"
        ),
    )

    result = CliRunner().invoke(cli.app, ["docker-sweep"])

    assert result.exit_code == INFRASTRUCTURE_EXIT_CODE
    assert '"error_code": "INFRASTRUCTURE_ERROR"' in result.stdout


def test_run_project_carries_a_typed_infrastructure_failure_across_the_process_boundary(
    monkeypatch, tmp_path,
) -> None:
    """I-3: `ServiceStartupError` is raised before the graph, so no report is
    ever written. Without a distinct exit status the typed code died with the
    process and the scorer saw exactly what it sees for an ASET crash."""
    from engineering_team.services import ServiceStartupError

    def refuse(*_args, **_kwargs):
        raise ServiceStartupError(
            "INFRASTRUCTURE_ERROR: the pre-run Docker sweep never got an answer"
        )

    monkeypatch.setattr(cli, "run_on_project", refuse)
    report = tmp_path / "report.json"

    result = CliRunner().invoke(cli.app, [
        "run-project", str(tmp_path), "--spec", "add endpoint",
        "--report-path", str(report),
    ])

    assert result.exit_code == INFRASTRUCTURE_EXIT_CODE
    assert not report.exists()
    # The operator still sees why; the scorer never reads this text.
    assert "the pre-run Docker sweep never got an answer" in result.stderr


def test_run_project_does_not_dress_any_other_failure_as_infrastructure(
    monkeypatch, tmp_path,
) -> None:
    """The CLI's own half of the mapping: only `ServiceStartupError` becomes the
    infrastructure status; anything else stays an uncaught exception.

    This patches `run_on_project`, so it says nothing about *which* failures
    reach the CLI as `ServiceStartupError`. That half -- an ASET bug during
    stack startup must not arrive wrapped -- is pinned on the real startup
    path in `tests/mcp/test_apply_infrastructure.py`
    (`test_run_project_exits_as_a_crash_for_an_aset_bug_during_stack_startup`)."""

    def crash(*_args, **_kwargs):
        raise RuntimeError("workflow completed without a terminal state")

    monkeypatch.setattr(cli, "run_on_project", crash)

    result = CliRunner().invoke(cli.app, [
        "run-project", str(tmp_path), "--spec", "add endpoint",
        "--report-path", str(tmp_path / "report.json"),
    ])

    assert result.exit_code not in (0, INFRASTRUCTURE_EXIT_CODE)
    assert isinstance(result.exception, RuntimeError)


def test_the_infrastructure_exit_status_does_not_collide_with_click_or_python() -> None:
    """0 is a completed CLI, 1 an uncaught exception or abort, 2 a usage error."""

    assert INFRASTRUCTURE_EXIT_CODE not in (0, 1, 2)
