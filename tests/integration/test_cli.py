from typer.testing import CliRunner

from engineering_team import cli
from engineering_team.contracts.enums import ErrorCode


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

    assert result.exit_code != 0
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
