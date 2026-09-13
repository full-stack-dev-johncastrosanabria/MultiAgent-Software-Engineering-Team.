"""A failed or ambiguous probe must never leave or delete someone else's ref."""

import importlib.util
import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "evaluation/benchmarks/ghcycle/probe_shallow_push.py"


@pytest.mark.parametrize("push_result", [0, 1, "timeout", "foreign"])
def test_probe_cleanup_is_leased_to_its_own_commit(tmp_path, monkeypatch, push_result):
    spec = importlib.util.spec_from_file_location("shallow_probe", SCRIPT)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    monkeypatch.setattr(probe, "__file__", str(tmp_path / "probe.py"))
    root = tmp_path / "checkout"
    root.mkdir()
    remote = {"oid": "other" if push_result == "foreign" else "own"}
    pushes = []

    @contextmanager
    def checkout(*args, **kwargs):
        assert kwargs["depth"] == 1
        try:
            yield root
        finally:
            shutil.rmtree(root)

    def checked(workspace, *args):
        if args == ("rev-parse", "--is-shallow-repository"):
            return "true"
        if args == ("rev-parse", "HEAD"):
            return "own"
        if args[0] == "ls-remote":
            return f"{remote['oid']}\t{args[-1]}" if remote["oid"] else ""
        if args[0] == "diff-tree":
            return ".aset-probe/example.txt"
        return ""

    def git(workspace, *args):
        pushes.append(args)
        if args[-1].startswith(":"):
            assert args[1] == f"--force-with-lease={args[-1][1:]}:own"
            remote["oid"] = ""
            return subprocess.CompletedProcess(args, 0, "", "")
        assert args[1].endswith(":")  # Creation requires an absent ref.
        if push_result == "timeout":
            raise subprocess.TimeoutExpired("git push", 300)
        code = push_result if isinstance(push_result, int) else 1
        return subprocess.CompletedProcess(args, code, "", "")

    monkeypatch.setattr(probe, "ephemeral_checkout", checkout)
    monkeypatch.setattr(probe, "_checked", checked)
    monkeypatch.setattr(probe, "_git", git)

    assert probe.main() == (0 if push_result == 0 else 1)
    report = json.loads((tmp_path / "results/shallow-push.json").read_text())
    assert report["checkout_removed"] is True
    if push_result == "foreign":
        assert len(pushes) == 1
        assert report["remote_ref_absent"] is False
        assert remote["oid"] == "other"
    else:
        assert len(pushes) == 2
        assert report["remote_ref_absent"] is True
        assert report["cleanup_returncode"] == 0
