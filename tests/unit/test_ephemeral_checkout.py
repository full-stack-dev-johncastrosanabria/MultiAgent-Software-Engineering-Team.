import subprocess
from pathlib import Path

import pytest

from engineering_team.ephemeral_checkout import ephemeral_checkout


def _origin(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def test_the_checkout_is_a_clone_of_the_named_repository(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(upstream)], check=True)
    (upstream / "README.md").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(upstream), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(upstream), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )

    with ephemeral_checkout(str(upstream)) as root:
        assert (root / ".git").is_dir()
        assert (root / "README.md").read_text(encoding="utf-8") == "original\n"
        assert _origin(root) == str(upstream)
        captured = root

    assert not captured.exists()


def test_the_checkout_is_removed_even_when_the_body_raises(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(upstream)], check=True)
    (upstream / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(upstream), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(upstream), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )

    captured = None
    with (
        pytest.raises(RuntimeError, match="the run failed"),
        ephemeral_checkout(str(upstream)) as root,
    ):
        captured = root
        raise RuntimeError("the run failed")

    assert captured is not None
    assert not captured.exists()


def test_a_clone_that_fails_leaves_no_directory_behind(tmp_path):
    with (
        pytest.raises(RuntimeError) as failure,
        ephemeral_checkout(str(tmp_path / "there-is-no-repository-here")),
    ):
        pass
    # The message names the operation, never the URL's credentials.
    assert "clone" in str(failure.value)


from typer.testing import CliRunner

from engineering_team.cli import app


def test_the_cli_refuses_a_path_and_a_repository_at_once():
    result = CliRunner().invoke(
        app, ["run-project", "some/path", "--repo", "https://example.test/r.git",
              "--spec", "x"],
    )
    assert result.exit_code != 0
    assert "not both" in result.output


def test_the_cli_refuses_neither_a_path_nor_a_repository():
    result = CliRunner().invoke(app, ["run-project", "--spec", "x"])
    assert result.exit_code != 0
    assert "a project path or --repo" in result.output


def test_the_cli_runs_against_the_checkout_it_cloned(monkeypatch, tmp_path):
    seen: dict[str, object] = {}

    def fake_run_on_project(settings, *, project_path, **kwargs):
        seen["path"] = Path(project_path)
        seen["existed"] = Path(project_path).exists()
        return {"status": "ok"}

    from contextlib import contextmanager

    @contextmanager
    def fake_checkout(url, *, depth=1):
        seen["url"] = url
        root = tmp_path / "clone"
        root.mkdir()
        yield root

    monkeypatch.setattr("engineering_team.cli.run_on_project", fake_run_on_project)
    monkeypatch.setattr("engineering_team.cli.ephemeral_checkout", fake_checkout)

    result = CliRunner().invoke(
        app, ["run-project", "--repo", "https://example.test/r.git", "--spec", "x"],
    )
    assert result.exit_code == 0, result.output
    assert seen["url"] == "https://example.test/r.git"
    assert seen["existed"] is True


from engineering_team.apply_run import tool_outcomes
from engineering_team.contracts.models import AgentRole, ToolResult, ToolStatus


def test_tool_outcomes_names_every_tool_and_its_status():
    results = [
        ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING,
            status=ToolStatus.UNAVAILABLE, input_summary="", output_summary="",
            duration_ms=0, error="venv creation failed in container",
        ),
        ToolResult(
            tool_name="get_diff", allowed_role=AgentRole.DEVELOPER,
            status=ToolStatus.SUCCESS, input_summary="", output_summary="",
            duration_ms=12,
        ),
    ]
    assert tool_outcomes(results) == [
        {"tool": "run_tests", "status": "UNAVAILABLE"},
        {"tool": "get_diff", "status": "SUCCESS"},
    ]
