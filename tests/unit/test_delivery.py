"""Work leaves this system as a branch and a pull request (ADR 6).

Everything before this was inward-facing: containers, closed networks, evidence.
This is the first capability that acts on someone's account, under their name,
in a way that is awkward to undo. The tests below are mostly about refusing.

The remote here is a bare repository on disk, so cloning, branching, committing
and pushing are exercised for real while nothing reaches GitHub.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engineering_team.delivery import (
    DeliveryRefused,
    GitDelivery,
    Proposal,
    clone_repository,
    infrastructure_proposal,
)

PROPOSAL = Proposal(
    branch="aset/add-compose",
    title="Add a compose file for local development",
    body="Derived from the connection strings this project declares.",
    files={"docker-compose.yml": "services: {}\n", ".env.example": "DB_PASSWORD=change-me\n"},
    run_id="run-1",
)


def _bare_remote(tmp_path: Path) -> Path:
    """A repository with one commit on `main`, served from disk."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "seed"
    work.mkdir()
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    run = lambda *a, **k: subprocess.run(a, cwd=work, check=True, capture_output=True)
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "aset@example.invalid")
    run("git", "config", "user.name", "ASET")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "seed")
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(origin)], check=True)
    return origin


# -- refusals ----------------------------------------------------------------


def test_nothing_leaves_without_an_explicit_confirmation(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    with pytest.raises(DeliveryRefused, match="confirm"):
        GitDelivery().push(checkout, PROPOSAL, confirmed=False)


def test_the_default_branch_is_never_a_target(tmp_path: Path) -> None:
    """The whole safety of this is that a branch can be deleted."""
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    for name in ("main", "master", "HEAD"):
        with pytest.raises(DeliveryRefused, match="branch"):
            GitDelivery().push(
                checkout, Proposal(name, "t", "b", {"a.txt": "x"}, "r"), confirmed=True
            )


def test_a_branch_outside_the_reserved_namespace_is_refused(tmp_path: Path) -> None:
    """Everything this system creates is identifiable and removable as a group."""
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    with pytest.raises(DeliveryRefused, match="aset/"):
        GitDelivery().push(
            checkout, Proposal("feature/x", "t", "b", {"a.txt": "x"}, "r"), confirmed=True
        )


def test_a_branch_name_that_could_be_an_argument_is_refused(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    for hostile in ("aset/--upload-pack=x", "aset/a b", "aset/..", "aset/x\ny"):
        with pytest.raises(DeliveryRefused):
            GitDelivery().push(
                checkout, Proposal(hostile, "t", "b", {"a.txt": "x"}, "r"), confirmed=True
            )


def test_a_file_path_escaping_the_repository_is_refused(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    with pytest.raises(DeliveryRefused, match="outside"):
        GitDelivery().push(
            checkout,
            Proposal("aset/x", "t", "b", {"../escaped.txt": "x"}, "r"),
            confirmed=True,
        )


def test_a_proposal_carrying_a_secret_is_refused(tmp_path: Path) -> None:
    """A pull request body is durable and, on a public repository, public."""
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    leaked = Proposal(
        "aset/x", "t", "connect with password=hunter2", {"a.txt": "x"}, "r",
    )
    with pytest.raises(DeliveryRefused, match="secret"):
        GitDelivery().push(checkout, leaked, confirmed=True)


# -- the happy path ----------------------------------------------------------


def test_a_confirmed_proposal_reaches_the_remote_on_its_own_branch(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")

    GitDelivery().push(checkout, PROPOSAL, confirmed=True)

    branches = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=origin, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert "aset/add-compose" in branches
    assert "main" in branches


def test_the_default_branch_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=origin, capture_output=True, text=True, check=True
    ).stdout
    checkout = clone_repository(str(origin), tmp_path / "work")

    GitDelivery().push(checkout, PROPOSAL, confirmed=True)

    after = subprocess.run(
        ["git", "rev-parse", "main"], cwd=origin, capture_output=True, text=True, check=True
    ).stdout
    assert before == after


def test_the_branch_carries_exactly_the_proposed_files(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")

    GitDelivery().push(checkout, PROPOSAL, confirmed=True)

    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "aset/add-compose"],
        cwd=origin, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert "docker-compose.yml" in listed
    assert ".env.example" in listed
    assert "README.md" in listed, "the branch must build on the project, not replace it"


def test_the_commit_says_what_made_it(tmp_path: Path) -> None:
    """A change nobody can trace to a run is a change nobody can audit."""
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")

    GitDelivery().push(checkout, PROPOSAL, confirmed=True)

    message = subprocess.run(
        ["git", "log", "-1", "--format=%B", "aset/add-compose"],
        cwd=origin, capture_output=True, text=True, check=True,
    ).stdout
    assert "run-1" in message
    assert "ASET" in message


def test_delivering_twice_updates_the_same_branch(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    GitDelivery().push(checkout, PROPOSAL, confirmed=True)
    second = Proposal(
        PROPOSAL.branch, PROPOSAL.title, PROPOSAL.body,
        {"docker-compose.yml": "services: {revised: {}}\n"}, "run-2",
    )
    GitDelivery().push(checkout, second, confirmed=True)

    content = subprocess.run(
        ["git", "show", "aset/add-compose:docker-compose.yml"],
        cwd=origin, capture_output=True, text=True, check=True,
    ).stdout
    assert "revised" in content


def test_a_placeholder_credential_is_exactly_what_should_be_published(tmp_path: Path) -> None:
    """The .env.example is the artefact; refusing it would defeat the delivery."""
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    artefact = Proposal(
        "aset/compose", "Add compose",
        "Derived from this project's own connection strings.",
        {
            "docker-compose.yml": "services:\n  postgres:\n    environment:\n"
                                  "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n",
            ".env.example": "POSTGRES_PASSWORD=change-me\n",
        },
        "run-9",
    )
    assert GitDelivery().push(checkout, artefact, confirmed=True) == "aset/compose"


def test_a_real_credential_beside_a_placeholder_is_still_refused(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    mixed = Proposal(
        "aset/mixed", "t", "b",
        {".env.example": "A_PASSWORD=change-me\nB_PASSWORD=actually-real\n"},
        "r",
    )
    with pytest.raises(DeliveryRefused, match="secret"):
        GitDelivery().push(checkout, mixed, confirmed=True)


# -- turning a derived topology into something reviewable --------------------


def test_a_project_needing_nothing_produces_no_proposal() -> None:
    """An empty pull request wastes the reviewer's time."""
    assert infrastructure_proposal("", "", run_id="r", engines=()) is None


def test_the_proposal_adds_files_and_edits_none() -> None:
    """The safest thing this system can offer back."""
    proposal = infrastructure_proposal(
        "services: {}\n", "PG_PASSWORD=change-me\n",
        run_id="r-1", engines=("postgres",),
    )
    assert set(proposal.files) == {"docker-compose.yml"}
    assert set(proposal.extends) == {".env.example"}
    assert proposal.branch.startswith("aset/")


def test_the_proposal_says_what_was_assumed() -> None:
    """Version choice is a guess, and a reviewer has to be able to see it."""
    proposal = infrastructure_proposal(
        "services: {}\n", "x=change-me\n", run_id="r", engines=("postgres", "mongo"),
    )
    assert "assumed" in proposal.body.lower()
    assert "postgres and mongo" in proposal.title


def test_the_proposal_names_the_files_it_read(tmp_path: Path) -> None:
    proposal = infrastructure_proposal(
        "services: {}\n", "x=change-me\n", run_id="r", engines=("mysql",),
        read_from=("api/appsettings.json",),
    )
    assert "api/appsettings.json" in proposal.body


def test_a_derived_proposal_passes_the_secret_check(tmp_path: Path) -> None:
    """The real artefacts, not a hand-written stand-in."""
    from engineering_team.topology import (
        derive_compose,
        environment_variables_example,
        extract_dependencies,
    )

    found = extract_dependencies(
        {"appsettings.json":
         '{"ConnectionStrings":{"Default":"Host=localhost;Port=5432;Database=d;Username=u;Password=real-secret"}}'}
    )
    proposal = infrastructure_proposal(
        derive_compose(found, mode="delivery"),
        environment_variables_example(found),
        run_id="r", engines=("postgres",),
    )
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    # The project's real password must not survive into the delivery artefact.
    assert "real-secret" not in proposal.files["docker-compose.yml"]
    assert GitDelivery().push(checkout, proposal, confirmed=True)


# -- never destroy what is already there -------------------------------------


def test_a_second_delivery_may_rewrite_the_file_it_added(tmp_path: Path) -> None:
    """What must not be replaced is the project's file, not our own."""
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")
    first = Proposal("aset/y", "t", "b", {"added.txt": "one\n"}, "r-1")
    GitDelivery().push(checkout, first, confirmed=True)
    GitDelivery().push(
        checkout, Proposal("aset/y", "t", "b", {"added.txt": "two\n"}, "r-2"),
        confirmed=True,
    )
    content = subprocess.run(
        ["git", "show", "aset/y:added.txt"],
        cwd=origin, capture_output=True, text=True, check=True,
    ).stdout
    assert "two" in content


def test_a_proposal_refuses_to_replace_an_existing_file(tmp_path: Path) -> None:
    """Measured the hard way: the first real pull request this system opened
    replaced a .env.example and deleted the documentation for a secret the
    project says has no default and fails at startup without."""
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")

    with pytest.raises(DeliveryRefused, match="already exists"):
        GitDelivery().push(
            checkout,
            Proposal("aset/x", "t", "b", {"README.md": "mine\n"}, "r"),
            confirmed=True,
        )


def test_an_extension_keeps_what_was_there(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")

    GitDelivery().push(
        checkout,
        Proposal("aset/x", "t", "b", {}, "r", extends={"README.md": "added line\n"}),
        confirmed=True,
    )

    content = subprocess.run(
        ["git", "show", "aset/x:README.md"],
        cwd=origin, capture_output=True, text=True, check=True,
    ).stdout
    assert "seed" in content, "the original content must survive"
    assert "added line" in content


def test_an_extension_creates_the_file_when_it_is_absent(tmp_path: Path) -> None:
    origin = _bare_remote(tmp_path)
    checkout = clone_repository(str(origin), tmp_path / "work")

    GitDelivery().push(
        checkout,
        Proposal("aset/x", "t", "b", {}, "r", extends={"NEW.md": "fresh\n"}),
        confirmed=True,
    )

    content = subprocess.run(
        ["git", "show", "aset/x:NEW.md"],
        cwd=origin, capture_output=True, text=True, check=True,
    ).stdout
    assert "fresh" in content


def test_the_infrastructure_proposal_extends_the_env_example() -> None:
    """`.env.example` usually exists and documents more than a database."""
    proposal = infrastructure_proposal(
        "services: {}\n", "PG_PASSWORD=change-me\n", run_id="r", engines=("postgres",),
    )
    assert "docker-compose.yml" in proposal.files
    assert ".env.example" in proposal.extends
    assert ".env.example" not in proposal.files


# -- choosing a delivery backend ---------------------------------------------


def test_delivery_is_off_unless_configured() -> None:
    """Outward-facing capabilities need two keys: configuration and a per-run
    confirmation. The default supplies neither."""
    from engineering_team.config import Settings
    from engineering_team.delivery import build_delivery

    assert Settings().delivery_backend == "none"
    assert build_delivery(Settings()) is None


def test_an_unknown_backend_is_refused_rather_than_guessed() -> None:
    from engineering_team.config import Settings
    from engineering_team.delivery import build_delivery

    with pytest.raises(DeliveryRefused, match="unknown delivery_backend"):
        build_delivery(Settings(delivery_backend="carrier-pigeon"))


def test_the_mcp_backend_requires_a_token() -> None:
    from engineering_team.config import Settings
    from engineering_team.delivery import build_delivery

    with pytest.raises(DeliveryRefused, match="token"):
        build_delivery(Settings(delivery_backend="mcp", github_personal_access_token=""))


def test_the_token_never_reaches_a_command_line() -> None:
    """`-e NAME` forwards the variable; `-e NAME=value` would put the secret
    where any process listing shows it."""
    from engineering_team.delivery import GitHubMCPPullRequests

    command = GitHubMCPPullRequests(token="super-secret-value").server_command()
    assert "super-secret-value" not in " ".join(command)
    assert "-e" in command
    assert command[command.index("-e") + 1] == "GITHUB_PERSONAL_ACCESS_TOKEN"


def test_both_backends_share_the_same_refusals() -> None:
    """A second backend must not become a second policy."""
    from engineering_team.delivery import GitHubMCPPullRequests

    backend = GitHubMCPPullRequests(token="t")
    with pytest.raises(DeliveryRefused, match="confirmation"):
        backend.open(Path("."), PROPOSAL, confirmed=False)
    with pytest.raises(DeliveryRefused, match="branch"):
        backend.open(
            Path("."), Proposal("main", "t", "b", {"a.txt": "x"}, "r"), confirmed=True
        )
