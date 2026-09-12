"""Infrastructure the project never declared, delivered instead of improvised.

ADR 18. The behaviours under test are the ones the record says were lost: that
a derived topology becomes a pull request instead of a deleted temporary file,
that it arrives on its own, that the functional delivery stacks on it, and that
the stacked body says what its evidence is worth.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engineering_team import delivery_check, infrastructure_prerequisite
from engineering_team.delivery import DeliveryRefused, GitDelivery, Proposal
from engineering_team.delivery_check import DeliveryCheck
from engineering_team.infrastructure_prerequisite import (
    DeliveredInfrastructure,
    Prerequisite,
    deliver,
    detect,
    stacked_body,
)

COMPOSE = "services:\n  postgres:\n    image: postgres@sha256:aa\n"
ENV_EXAMPLE = "POSTGRES_PASSWORD=change-me\nPOSTGRES_USER=aset\n"


class _Stack:
    """Stands in for ServiceStack, which needs a real compose and a daemon."""

    def __init__(self, *, derived: bool, services=("postgres",), compose=COMPOSE):
        self.derived = derived
        self.services = services
        self._compose = compose

    def delivery_artifacts(self):
        return self._compose, ENV_EXAMPLE


def test_a_derived_topology_is_a_blocking_prerequisite(tmp_path: Path) -> None:
    (tmp_path / "application.yaml").write_text(
        "spring:\n  datasource:\n    url: jdbc:postgresql://localhost:5432/orders\n"
    )
    found = detect(_Stack(derived=True), tmp_path)
    assert found is not None
    assert found.engines == ("postgres",)
    assert found.compose == COMPOSE
    # PR #1 said which files the values came from. That sentence is most of why
    # it was reviewable, so the file that named the engine is carried through.
    assert "application.yaml" in found.read_from


def test_a_project_that_declares_its_own_topology_is_not_blocked(tmp_path: Path) -> None:
    assert detect(_Stack(derived=False), tmp_path) is None


def test_a_project_that_needs_no_services_produces_no_proposal(tmp_path: Path) -> None:
    """The right answer is nothing, not an empty pull request."""
    assert detect(_Stack(derived=True, services=(), compose=""), tmp_path) is None


def test_the_proposal_adds_two_files_and_edits_none() -> None:
    prerequisite = Prerequisite(
        engines=("postgres",), read_from=("application.yaml",),
        compose=COMPOSE, env_example=ENV_EXAMPLE,
    )
    proposal = prerequisite.proposal("apply-1")
    assert proposal is not None
    assert set(proposal.files) == {"docker-compose.yml"}
    # `.env.example` is appended to, never replaced: a project usually has one
    # already, documenting more than a database.
    assert set(proposal.extends) == {".env.example"}
    assert proposal.updates == {}
    assert "application.yaml" in proposal.body
    assert "assumed" in proposal.body.lower()


def test_the_infrastructure_pull_request_opens_before_the_functional_one() -> None:
    order: list[str] = []

    class _Git(GitDelivery):
        def push(self, repository, proposal, *, confirmed, base=""):
            order.append(f"push:{proposal.branch}:{base}")
            return proposal.branch

    class _Backend:
        def open(self, repository, proposal, *, confirmed, base=""):
            order.append(f"open:{proposal.branch}:{base}")
            return "https://example.invalid/pull/1"

    prerequisite = Prerequisite(
        engines=("postgres",), read_from=(), compose=COMPOSE, env_example=ENV_EXAMPLE,
    )
    delivered = deliver(
        Path("/tmp"), prerequisite, run_id="apply-1",
        backend=_Backend(), confirmed=True, git=_Git(),
    )
    assert delivered.branch == "aset/compose-postgres"
    assert delivered.url == "https://example.invalid/pull/1"
    assert order == ["push:aset/compose-postgres:", "open:aset/compose-postgres:"]


def test_an_undeliverable_prerequisite_is_refused_not_degraded() -> None:
    """ADR 18: either delivered or refused. There is no quiet third path."""
    empty = Prerequisite(engines=(), read_from=(), compose="", env_example="")
    with pytest.raises(DeliveryRefused):
        deliver(Path("/tmp"), empty, run_id="apply-1", backend=None, confirmed=True)


def test_the_stacked_body_says_the_evidence_describes_unreviewed_infrastructure() -> None:
    delivered = DeliveredInfrastructure(
        branch="aset/compose-postgres", engines=("postgres",),
        url="https://example.invalid/pull/1",
    )
    body = stacked_body("Reviewer-APPROVED implementation.", delivered)
    assert "Reviewer-APPROVED implementation." in body
    assert "https://example.invalid/pull/1" in body
    assert "no human has reviewed" in body
    assert "re-run" in body


def test_a_delivery_may_only_be_stacked_on_a_branch_this_system_authored() -> None:
    """A stacking base is an argument, never a field the proposal controls."""
    proposal = Proposal(
        branch="aset/apply-1", title="t", body="b",
        files={"a.txt": "x"}, run_id="apply-1",
    )
    assert "base" not in proposal.__dataclass_fields__
    for refused in ("main", "master", "someone-elses-branch", "aset/apply-1"):
        with pytest.raises(DeliveryRefused):
            GitDelivery._check_stacking_base(refused, proposal.branch)
    GitDelivery._check_stacking_base("aset/compose-postgres", proposal.branch)


def _approved_state(prerequisite: Prerequisite | None) -> dict:
    from engineering_team.contracts.enums import ActionMode, ReviewerStatus
    from engineering_team.contracts.models import ImplementationResult, ReviewerDecision

    return {
        "run_id": "apply-18",
        "implementation": ImplementationResult(
            action_mode=ActionMode.APPLIED,
            changed_files=["app.py"],
            diff="add endpoint",
            evidence=["mcp://repository/update_file"],
            validation_result="ok",
            security_surface_changed=False,
            file_contents={"app.py": "x = 2\n"},
        ),
        "review": ReviewerDecision(
            status=ReviewerStatus.APPROVED, score=100,
            subscores={
                "requirements": 100, "architecture": 100, "security": 100,
                "testing": 100, "implementation": 100, "rag_grounding": 100,
            },
            reason="validated evidence satisfies acceptance checks", confidence=1,
        ),
        "tool_results": [], "errors": [], "final_status": "APPROVED",
        "route_history": [], "iteration": 1, "model_usage": [],
        "human_review_required": False,
        "infrastructure_prerequisite": prerequisite,
    }


def _run_with(prerequisite, tmp_path, monkeypatch) -> tuple[dict, list[str]]:
    from types import SimpleNamespace

    from engineering_team.apply_run import run_on_project
    from engineering_team.config import Settings

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "engineering_team.apply_run.execute_on_project",
        lambda *a, **k: (
            _approved_state(prerequisite),
            SimpleNamespace(trace_id="trace-18", live=False),
            0.01, False,
        ),
    )
    order: list[str] = []

    class _Git:
        def push(self, repository, proposal, *, confirmed, base=""):
            order.append(f"push:{proposal.branch}:base={base}")
            _Git.last = proposal
            return proposal.branch

    class _Backend:
        def open(self, repository, proposal, *, confirmed, base=""):
            order.append(f"open:{proposal.branch}:base={base}")
            _Backend.last = proposal
            return f"https://example.invalid/pull/{len(order)}"

    monkeypatch.setattr("engineering_team.apply_run.GitDelivery", _Git)
    monkeypatch.setattr(
        "engineering_team.apply_run.build_delivery", lambda settings: _Backend()
    )
    evidence = run_on_project(
        Settings(delivery_backend="gh"),
        project_path=project,
        specification="add endpoint",
        authorize_writes=True,
        confirm_delivery=True,
    )
    return evidence, order, _Backend


def test_the_run_delivers_infrastructure_first_then_stacks_the_functional_work(
    tmp_path, monkeypatch
) -> None:
    prerequisite = Prerequisite(
        engines=("postgres",), read_from=("application.yaml",),
        compose=COMPOSE, env_example=ENV_EXAMPLE,
    )
    evidence, order, backend = _run_with(prerequisite, tmp_path, monkeypatch)

    assert order == [
        "push:aset/compose-postgres:base=",
        "open:aset/compose-postgres:base=",
        "push:aset/apply-18:base=aset/compose-postgres",
        "open:aset/apply-18:base=aset/compose-postgres",
    ]
    assert evidence["infrastructure_branch"] == "aset/compose-postgres"
    assert evidence["infrastructure_pr_url"] == "https://example.invalid/pull/2"
    assert evidence["infrastructure_prerequisite"] == {
        "engines": ["postgres"], "read_from": ["application.yaml"],
    }
    # The second pull request says what its green suite is worth.
    assert "no human has reviewed" in backend.last.body


def test_a_project_with_its_own_compose_delivers_exactly_one_pull_request(
    tmp_path, monkeypatch
) -> None:
    evidence, order, _ = _run_with(None, tmp_path, monkeypatch)
    assert order == ["push:aset/apply-18:base=", "open:aset/apply-18:base="]
    assert "infrastructure_branch" not in evidence
    assert evidence["infrastructure_prerequisite"] is None


def test_a_refused_infrastructure_delivery_stops_the_run(
    tmp_path, monkeypatch
) -> None:
    """The functional pull request must not survive the infrastructure's refusal.

    This run's suite is green against a database this run brought up. If the
    compose file that describes it is refused, there is no branch to stack on,
    nothing for the body to point at, and no reviewer who has seen the
    environment the evidence describes -- and the old behaviour pushed anyway,
    to the default branch, with a body that said none of it. ADR 18 says the run
    stops. Nothing is pushed at all.
    """
    monkeypatch.setattr(
        infrastructure_prerequisite,
        "validate_delivered_compose",
        lambda compose, env_example, **_: DeliveryCheck(
            performed=True, valid=False, error="the delivered compose file is empty"
        ),
    )
    prerequisite = Prerequisite(
        engines=("postgres",), read_from=("application.yaml",),
        compose=COMPOSE, env_example=ENV_EXAMPLE,
    )
    evidence, order, _ = _run_with(prerequisite, tmp_path, monkeypatch)

    assert order == []
    assert "delivery_branch" not in evidence
    assert "delivery_pr_url" not in evidence
    assert "infrastructure_branch" not in evidence
    # Recorded, and -- unlike before -- read by the code that decides to push.
    assert "the delivered compose file is empty" in (
        evidence["infrastructure_delivery_error"]
    )
    assert "nothing functional was pushed" in evidence["delivery_blocked"]
    assert evidence["delivery_error"] == evidence["delivery_blocked"]


def test_a_stacked_branch_is_really_cut_from_the_infrastructure_branch(
    tmp_path,
) -> None:
    """The claim is about git, so it is checked against git."""
    import subprocess

    repository = tmp_path / "repo"
    repository.mkdir()

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    git("init", "--quiet", "--initial-branch", "main")
    git("config", "user.email", "test@localhost.invalid")
    git("config", "user.name", "test")
    (repository / "README.md").write_text("project\n")
    git("add", "README.md")
    git("commit", "--quiet", "-m", "initial")
    git("checkout", "--quiet", "-b", "aset/compose-postgres")
    (repository / "docker-compose.yml").write_text(COMPOSE)
    git("add", "docker-compose.yml")
    git("commit", "--quiet", "-m", "compose")
    git("checkout", "--quiet", "main")

    git("checkout", "-B", "aset/apply-18", "aset/compose-postgres")
    # The functional branch contains the infrastructure, which is exactly why
    # ADR 18 refuses to call the second delivery independent.
    assert (repository / "docker-compose.yml").exists()
    assert git("merge-base", "aset/apply-18", "aset/compose-postgres") == git(
        "rev-parse", "aset/compose-postgres"
    )


# -- the delivered compose is executed before a person receives it ------------
#
# ADR 18 delivers the `delivery` rendering, and the run only ever starts the
# `run` one. These cover the gap: what the reviewer receives is resolved by the
# runtime first, and the body says exactly how much that is worth.
#
# No test here launches Docker. `delivery_check` talks to the runtime through
# the seam the rest of the repository already uses -- a `runtime` argument plus
# module-level `subprocess`/`shutil` -- and these monkeypatch it, exactly as
# `tests/unit/test_docker_labels.py` does for the sweep.

DELIVERED_COMPOSE = (
    "services:\n"
    "  postgres:\n"
    "    image: postgres@sha256:aa\n"
    "    environment:\n"
    "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n"
    "    ports:\n"
    '      - "5432:5432"\n'
    "    volumes:\n"
    "      - ./init.sql:/docker-entrypoint-initdb.d/10-init.sql:ro\n"
)


@pytest.fixture(autouse=True)
def _no_runtime_from_a_unit_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this file may reach a container runtime.

    `deliver` now validates before it proposes, so every existing test through
    it would otherwise shell out to `docker compose config`. A test whose result
    depends on what is installed on the machine running it is not a unit test;
    the tests below that care about the answer replace this stub with their own.
    """
    monkeypatch.setattr(
        infrastructure_prerequisite,
        "validate_delivered_compose",
        lambda compose, env_example, **_: DeliveryCheck(performed=True, valid=True),
    )


def _runtime(monkeypatch: pytest.MonkeyPatch, handler, *, installed: bool = True):
    monkeypatch.setattr(
        delivery_check.shutil, "which",
        lambda _name: "/usr/bin/docker" if installed else None,
    )
    monkeypatch.setattr(delivery_check.subprocess, "run", handler)


def _delivered_body(check: DeliveryCheck, monkeypatch: pytest.MonkeyPatch) -> str:
    """The body of the pull request `deliver` would open, given this check."""
    bodies: list[str] = []

    class _Git(GitDelivery):
        def push(self, repository, proposal, *, confirmed, base=""):
            bodies.append(proposal.body)
            return proposal.branch

    monkeypatch.setattr(
        infrastructure_prerequisite,
        "validate_delivered_compose",
        lambda compose, env_example, **_: check,
    )
    prerequisite = Prerequisite(
        engines=("postgres",), read_from=(),
        compose=DELIVERED_COMPOSE, env_example=ENV_EXAMPLE,
    )
    deliver(
        Path("/tmp"), prerequisite, run_id="apply-1",
        backend=None, confirmed=True, git=_Git(),
    )
    return bodies[0]


def test_a_file_the_runtime_rejects_is_refused_not_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever `compose config` exits non-zero on blocks the delivery.

    A schema error, or the required form `${NAME:?message}` with nothing to
    resolve it. Not the optional form the delivery rendering actually emits --
    that one is the test below, and it is the reason this test is not the whole
    of the coverage.
    """
    def _rejected(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv, 1, "",
            'required variable "POSTGRES_PASSWORD" is missing a value\n',
        )

    _runtime(monkeypatch, _rejected)
    check = delivery_check.validate_delivered_compose(
        DELIVERED_COMPOSE, "# nothing declared\n"
    )
    assert check.performed is True
    assert check.valid is False
    assert "missing a value" in check.error

    monkeypatch.setattr(
        infrastructure_prerequisite,
        "validate_delivered_compose",
        lambda compose, env_example, **_: check,
    )
    prerequisite = Prerequisite(
        engines=("postgres",), read_from=(),
        compose=DELIVERED_COMPOSE, env_example=ENV_EXAMPLE,
    )
    with pytest.raises(DeliveryRefused, match="did not pass validation"):
        deliver(
            Path("/tmp"), prerequisite, run_id="apply-1",
            backend=None, confirmed=True, git=GitDelivery(),
        )


def test_a_variable_the_template_lost_is_refused_though_the_runtime_said_yes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure this whole check exists for, and the runtime cannot see it.

    `${POSTGRES_PASSWORD}` is Compose's optional form: with nothing to resolve
    it, Compose warns, substitutes the empty string, and exits 0. The runner in
    `evaluation/benchmarks/adr18` caught this against the operator's real daemon
    -- a template missing a key was delivered, with a body claiming its
    substitution had been resolved. The comparison, not the runtime, is what
    refuses it.
    """
    def _accepted_with_a_warning(argv, **_kwargs):
        if "ps" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(
            argv, 0, "",
            'warning: The "POSTGRES_PASSWORD" variable is not set. '
            "Defaulting to a blank string.\n",
        )

    _runtime(monkeypatch, _accepted_with_a_warning)
    check = delivery_check.validate_delivered_compose(
        DELIVERED_COMPOSE, "# the key this template used to declare is gone\n"
    )
    assert check.performed is True
    assert check.valid is False
    assert "${POSTGRES_PASSWORD}" in check.error

    monkeypatch.setattr(
        infrastructure_prerequisite,
        "validate_delivered_compose",
        lambda compose, env_example, **_: check,
    )
    prerequisite = Prerequisite(
        engines=("postgres",), read_from=(),
        compose=DELIVERED_COMPOSE, env_example="# nothing declared\n",
    )
    with pytest.raises(DeliveryRefused, match="did not pass validation"):
        deliver(
            Path("/tmp"), prerequisite, run_id="apply-1",
            backend=None, confirmed=True, git=GitDelivery(),
        )


def test_a_default_and_a_shell_escape_are_not_undeclared_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the comparison must not refuse, or it would refuse correct files.

    A reference carrying a default needs nothing from the template. `$$USER` is
    how the healthcheck writes a literal `$` for the shell inside the container
    -- the delivery rendering emits exactly that for postgres -- and Compose
    never resolves it, so neither does this.
    """
    def _clean(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    _runtime(monkeypatch, _clean)
    compose = (
        "services:\n"
        "  postgres:\n"
        "    image: postgres@sha256:aa\n"
        "    environment:\n"
        "      POSTGRES_DB: ${POSTGRES_DB:-orders}\n"
        "      POSTGRES_PORT: ${POSTGRES_PORT-5432}\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]\n'
    )
    check = delivery_check.validate_delivered_compose(compose, "# nothing\n")
    assert (check.performed, check.valid, check.error) == (True, True, "")


def test_a_port_already_in_use_is_named_in_the_body_and_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The busy port is on this machine, not on the reviewer's.

    Refusing would throw away a correct file because something local happens to
    hold 5432. Saying so turns an opaque bind error on their side into a line
    they have already read.
    """
    def _busy(argv, **_kwargs):
        if "ps" in argv:
            return subprocess.CompletedProcess(
                argv, 0, "0.0.0.0:5432->5432/tcp\n80/tcp\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    _runtime(monkeypatch, _busy)
    check = delivery_check.validate_delivered_compose(DELIVERED_COMPOSE, ENV_EXAMPLE)
    assert check.performed is True
    assert check.valid is True
    assert check.occupied_ports == ("5432",)

    body = _delivered_body(check, monkeypatch)
    assert "5432" in body
    assert "already" in body


def test_without_a_runtime_nothing_is_claimed_and_the_body_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silence must not read as a pass."""
    def _never_called(argv, **_kwargs):  # pragma: no cover - the point is it is not
        raise AssertionError("no runtime should have been invoked")

    _runtime(monkeypatch, _never_called, installed=False)
    check = delivery_check.validate_delivered_compose(DELIVERED_COMPOSE, ENV_EXAMPLE)
    assert check.performed is False

    body = _delivered_body(check, monkeypatch)
    assert "was not validated" in body
    assert "docker compose config" in body
    # There was no runtime. The note may say that, and only in this case.
    assert "No container runtime was available" in body


def test_a_runtime_that_cannot_be_spoken_to_is_not_called_a_missing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`performed=False` arrives by more than one road and the note must know.

    A `docker` on PATH whose daemon refuses the connection is not a machine
    without a container runtime, and telling the reviewer it was is a small lie
    they have no way to check. The redacted reason is quoted instead.
    """
    def _unreachable(argv, **_kwargs):
        raise OSError("cannot connect to the daemon at DOCKER_HOST=unix:///nope")

    _runtime(monkeypatch, _unreachable)
    check = delivery_check.validate_delivered_compose(DELIVERED_COMPOSE, ENV_EXAMPLE)
    assert check.performed is False
    assert check.error

    body = _delivered_body(check, monkeypatch)
    assert "was not validated" in body
    assert "could not be spoken to" in body
    assert check.error in body
    # The sentence that belongs to the other road must not appear on this one.
    assert "No container runtime was available" not in body


def test_a_clean_check_earns_the_partial_validation_sentence_and_no_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema and substitution. Not that anything starts, not that it is healthy."""
    def _clean(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    _runtime(monkeypatch, _clean)
    check = delivery_check.validate_delivered_compose(DELIVERED_COMPOSE, ENV_EXAMPLE)
    assert (check.performed, check.valid, check.occupied_ports) == (True, True, ())

    body = _delivered_body(check, monkeypatch)
    assert "every variable it interpolates has somewhere to come from" in body
    assert "no healthcheck was exercised" in body
    assert "was not validated" not in body


def test_the_synthetic_env_never_carries_a_value_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validating against the operator's real credentials would prove nothing.

    It would also write them to a file this module created. The values come
    from the template's keys and a literal marker, never from `os.environ`.
    """
    monkeypatch.setenv("POSTGRES_PASSWORD", "a-real-secret-from-this-shell")
    monkeypatch.setenv("POSTGRES_USER", "a-real-user-from-this-shell")
    seen: dict[str, str] = {}

    def _capture(argv, **_kwargs):
        if "--env-file" in argv:
            path = Path(argv[argv.index("--env-file") + 1])
            seen["env"] = path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    _runtime(monkeypatch, _capture)
    delivery_check.validate_delivered_compose(DELIVERED_COMPOSE, ENV_EXAMPLE)

    written = seen["env"]
    assert "a-real-secret-from-this-shell" not in written
    assert "a-real-user-from-this-shell" not in written
    # Not the template's example values either: those are documentation.
    assert "change-me" not in written
    assert written.splitlines() == [
        "POSTGRES_PASSWORD=PLACEHOLDER-FOR-VALIDATION",
        "POSTGRES_USER=PLACEHOLDER-FOR-VALIDATION",
    ]


def test_the_operators_shell_never_reaches_the_validation_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `.env` alone does not close this, and reading it would not show it.

    Compose resolves a variable from the process environment *before* it falls
    back to the `--env-file`, so a subprocess that inherits the operator's shell
    validates against the operator's shell no matter what the synthetic file
    says. Checked by hand against a real daemon:

        MYSQL_ROOT_PASSWORD=real-shell-secret docker compose \
            -f c.yml --env-file e.env config

    printed `MYSQL_ROOT_PASSWORD: real-shell-secret` with `e.env` holding the
    marker. The assertion is therefore on what the subprocess *receives*, not on
    what was written to disk -- the test that only read the file passed for the
    whole time the hole was open.
    """
    monkeypatch.setenv("POSTGRES_PASSWORD", "a-real-secret-from-this-shell")
    monkeypatch.setenv("POSTGRES_USER", "a-real-user-from-this-shell")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    seen: dict[str, dict[str, str] | None] = {}

    def _capture(argv, **kwargs):
        # Only the `config` call: `_ports_already_bound` shells out afterwards
        # and would otherwise be the invocation this test inspected.
        if "config" in argv:
            seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, "", "")

    _runtime(monkeypatch, _capture)
    delivery_check.validate_delivered_compose(DELIVERED_COMPOSE, ENV_EXAMPLE)

    passed = seen["env"]
    assert passed is not None, "the subprocess inherited os.environ"
    # The template wins over the shell, for every key the template declares.
    assert passed["POSTGRES_PASSWORD"] == delivery_check.PLACEHOLDER
    assert passed["POSTGRES_USER"] == delivery_check.PLACEHOLDER
    assert "a-real-secret-from-this-shell" not in passed.values()
    assert "a-real-user-from-this-shell" not in passed.values()
    # What is carried across is what the client needs to reach its daemon, and
    # a check that cannot reach the daemon is a check that did not run.
    assert passed["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert passed["PATH"] == os.environ["PATH"]


def test_a_variable_the_shell_holds_and_the_template_does_not_is_not_smuggled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shadowing the declared keys is not enough on its own.

    A compose file interpolating something the template forgot is already
    refused by `_undeclared_references`, but only because the environment does
    not answer for it either. An inherited shell would answer, the runtime would
    resolve the file, and the misaligned template would reach the reviewer.
    """
    monkeypatch.setenv("SOMETHING_ONLY_THIS_SHELL_HAS", "a-real-secret-from-this-shell")
    seen: dict[str, dict[str, str] | None] = {}

    def _capture(argv, **kwargs):
        # Only the `config` call: `_ports_already_bound` shells out afterwards
        # and would otherwise be the invocation this test inspected.
        if "config" in argv:
            seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, "", "")

    _runtime(monkeypatch, _capture)
    delivery_check.validate_delivered_compose(DELIVERED_COMPOSE, ENV_EXAMPLE)

    passed = seen["env"]
    assert passed is not None
    assert "SOMETHING_ONLY_THIS_SHELL_HAS" not in passed


def test_an_empty_delivered_compose_is_a_verdict_not_a_missing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`performed=False` would dress this as "no container runtime available".

    An empty file is something this check *knows* about the delivery, and the
    body a reviewer reads has to say the file is empty rather than blame a
    runtime that was installed all along.
    """
    def _never_called(argv, **_kwargs):  # pragma: no cover - the point is it is not
        raise AssertionError("an empty file must not reach the runtime")

    _runtime(monkeypatch, _never_called)
    check = delivery_check.validate_delivered_compose("   \n", ENV_EXAMPLE)

    assert (check.performed, check.valid) == (True, False)
    assert "empty" in check.error

    with pytest.raises(DeliveryRefused, match="empty"):
        _delivered_body(check, monkeypatch)
