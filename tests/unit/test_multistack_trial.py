import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def trial():
    path = Path(__file__).parents[2] / "evaluation/benchmarks/multistack/run_trial.py"
    spec = importlib.util.spec_from_file_location("multistack_trial", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_interval_uses_latest_probe_or_run_across_all_repositories(trial):
    probes = {"attempts": [{"ended_epoch": 1000}]}
    records = [{"case": "ingresos", "finished_epoch": 1100}]
    with pytest.raises(SystemExit, match="wait at least 0.1"):
        trial.require_experiment_interval(records, probes, 1279.9)
    trial.require_experiment_interval(records, probes, 1280)
    probes["attempts"].append({"ended_epoch": 1200})
    with pytest.raises(SystemExit, match="wait at least"):
        trial.require_experiment_interval(records, probes, 1280)


def test_unresolved_experiment_cannot_be_bypassed_by_a_later_record(trial):
    with pytest.raises(SystemExit, match="no terminal record"):
        trial.require_experiment_interval(
            [{"finished_epoch": None}, {"finished_epoch": 100}],
            {"attempts": []}, 10000,
        )


def test_crash_preserves_failure_evidence_and_terminal_journal(trial, tmp_path, monkeypatch):
    report = tmp_path / "failure.json"
    monkeypatch.setattr(sys, "argv", [
        "run_trial.py", "ingresos", "--workspace", str(tmp_path), "--report", str(report),
    ])
    monkeypatch.setattr(trial, "Settings", lambda **_: SimpleNamespace(gemini_api_key_2=None))
    # Past any saved credential probe; no provider or infrastructure is invoked.
    monkeypatch.setattr(trial.time, "time", lambda: 2_000_000_000)

    def crash(*args, **kwargs):
        raise ValueError("password=must-not-appear-in-evidence")

    monkeypatch.setattr(trial, "run_on_project", crash)
    with pytest.raises(ValueError):
        trial.main()
    evidence = json.loads(report.read_text())
    journal = json.loads((tmp_path / "experiments.json").read_text())
    assert evidence["final_status"] == "ERROR"
    assert evidence["exception_type"] == "ValueError"
    assert journal[-1]["finished_epoch"] == 2_000_000_000
    assert "must-not-appear" not in report.read_text()
    assert "must-not-appear" not in (tmp_path / "experiments.json").read_text()


def test_existing_report_is_never_overwritten(trial, tmp_path, monkeypatch):
    report = tmp_path / "prior.json"
    report.write_text('{"original": true}')
    monkeypatch.setattr(sys, "argv", [
        "run_trial.py", "northgate", "--workspace", str(tmp_path), "--report", str(report),
    ])
    with pytest.raises(SystemExit):
        trial.main()
    assert json.loads(report.read_text()) == {"original": True}
    assert not (tmp_path / "experiments.json").exists()
