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
    journal_path = tmp_path / "evidence/experiments.json"
    journal = json.loads(journal_path.read_text())
    assert evidence["final_status"] == "ERROR"
    assert evidence["exception_type"] == "ValueError"
    assert evidence.get("exception_message")
    assert evidence.get("raise_site")
    assert "process_path" in evidence
    assert "docker_which" in evidence
    assert journal[-1]["finished_epoch"] == 2_000_000_000
    assert journal[-1].get("exception_message")
    assert "must-not-appear" not in report.read_text()
    assert "must-not-appear" not in journal_path.read_text()


def test_existing_report_is_never_overwritten(trial, tmp_path, monkeypatch):
    report = tmp_path / "prior.json"
    report.write_text('{"original": true}')
    monkeypatch.setattr(sys, "argv", [
        "run_trial.py", "northgate", "--workspace", str(tmp_path), "--report", str(report),
    ])
    with pytest.raises(SystemExit):
        trial.main()
    assert json.loads(report.read_text()) == {"original": True}
    assert not (tmp_path / "evidence/experiments.json").exists()


def test_report_directory_cannot_bypass_interval(trial, tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "Settings", lambda **_: SimpleNamespace(gemini_api_key_2=None))
    monkeypatch.setattr(trial.time, "time", lambda: 2_000_000_000)
    calls = []

    def completed(**kwargs):
        calls.append(kwargs["project_path"])
        return {"final_status": "APPROVED"}

    monkeypatch.setattr(trial, "run_on_project", lambda _settings, **kw: completed(**kw))
    for index, case in enumerate(("ingresos", "northgate")):
        monkeypatch.setattr(sys, "argv", [
            "run_trial.py", case, "--workspace", str(tmp_path),
            "--report", str(tmp_path / f"reports-{index}/result.json"),
        ])
        if index == 0:
            trial.main()
        else:
            with pytest.raises(SystemExit, match="wait at least 180"):
                trial.main()
    assert len(calls) == 1
    journal = json.loads((tmp_path / "evidence/experiments.json").read_text())
    assert len(journal) == 1


def test_report_directory_cannot_bypass_running_experiment(trial, tmp_path, monkeypatch):
    import fcntl

    state_dir = tmp_path / "evidence"
    state_dir.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "run_trial.py", "interview", "--workspace", str(tmp_path),
        "--report", str(tmp_path / "other-reports/result.json"),
    ])
    with (state_dir / "experiments.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            trial.main()
