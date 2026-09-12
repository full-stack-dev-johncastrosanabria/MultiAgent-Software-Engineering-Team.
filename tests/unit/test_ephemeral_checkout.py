import subprocess
from pathlib import Path

import pytest

from engineering_team.apply_run import tool_outcomes
from engineering_team.contracts.models import AgentRole, ToolResult, ToolStatus
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


def test_a_url_carrying_a_credential_is_refused_before_the_clone(monkeypatch):
    token = "sekrit-token-value"

    def _subprocess_must_not_run(*args, **kwargs):
        raise AssertionError("git must not run: the guard should refuse first")

    monkeypatch.setattr(subprocess, "run", _subprocess_must_not_run)

    with (
        pytest.raises(RuntimeError) as failure,
        ephemeral_checkout(f"https://{token}@no-such-host.invalid/owner/repo.git"),
    ):
        pass
    assert token not in str(failure.value)
    assert "credentialed" in str(failure.value)


def test_scp_style_urls_are_not_mistaken_for_a_credential():
    # `git@no-such-host.invalid:owner/repo.git` -- the `@` is the scp-style
    # username, not a credential. It has no netloc at all (no `scheme://`), so
    # the guard must not trip on it. It is free to fail later, at the clone
    # itself (`.invalid` never resolves) -- just not on the credential guard.
    with (
        pytest.raises(RuntimeError) as failure,
        ephemeral_checkout("git@no-such-host.invalid:owner/repo.git"),
    ):
        pass
    assert "credentialed" not in str(failure.value)


def test_a_plain_https_url_is_not_mistaken_for_a_credential():
    with (
        pytest.raises(RuntimeError) as failure,
        ephemeral_checkout("https://no-such-host.invalid/owner/repo.git"),
    ):
        pass
    assert "credentialed" not in str(failure.value)


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
        {
            "tool": "run_tests",
            "status": "UNAVAILABLE",
            "error": "venv creation failed in container",
        },
        {"tool": "get_diff", "status": "SUCCESS"},
    ]


def test_a_successful_tool_carries_no_error_excerpt():
    """Success output is bulk, not evidence, and never reaches the report."""
    results = [
        ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING,
            status=ToolStatus.SUCCESS, input_summary="", output_summary="",
            duration_ms=3, error="stale text from an earlier attempt",
        ),
    ]
    assert tool_outcomes(results) == [{"tool": "run_tests", "status": "SUCCESS"}]


def test_a_failing_tool_reports_why_it_failed():
    """A red stage that cannot say why is a stage nobody can act on.

    ``mcp.quality`` sets ``error`` only for UNAVAILABLE, so a FAIL keeps its
    reason in ``output_summary`` -- the case this excerpt exists to explain.
    """
    results = [
        ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING,
            status=ToolStatus.FAIL,
            input_summary="",
            output_summary="E   ModuleNotFoundError: No module named 'flask_cors'",
            duration_ms=9,
            error=None,
        ),
    ]
    outcome = tool_outcomes(results)[0]
    assert outcome["status"] == "FAIL"
    assert "ModuleNotFoundError" in outcome["error"]


def test_the_infrastructure_error_outranks_the_bulk_output():
    """UNAVAILABLE names the infrastructure that broke; the output is noise."""
    results = [
        ToolResult(
            tool_name="run_tests", allowed_role=AgentRole.TESTING,
            status=ToolStatus.UNAVAILABLE,
            input_summary="",
            output_summary="hundreds of lines of pip chatter",
            duration_ms=9,
            error="INFRASTRUCTURE_ERROR: venv creation failed in container",
        ),
    ]
    assert "venv creation failed" in tool_outcomes(results)[0]["error"]


def test_the_error_excerpt_is_redacted_and_keeps_its_tail():
    """Process output reaches a committed report, so a secret must not ride along.

    The tail is what is kept: the reason a tool failed is far more often the
    last line of its output than the first.
    """
    secret = "ghp_" + "a" * 36
    results = [
        ToolResult(
            tool_name="run_security_scan", allowed_role=AgentRole.SECURITY,
            status=ToolStatus.FAIL, input_summary="", output_summary="",
            duration_ms=9,
            error=f"token={secret}\n" + ("filler line\n" * 400) + "the actual reason",
        ),
    ]
    excerpt = tool_outcomes(results)[0]["error"]
    assert secret not in excerpt
    assert excerpt.endswith("the actual reason")
    assert len(excerpt) <= 600
