"""How work leaves this system (ADR 6).

Everything else here faces inward: containers, closed networks, evidence that
never travels. This is the first capability that acts on someone's account, under
their name, in a way that is awkward to undo -- so most of this module is about
refusing.

The safety rests on one property: everything created is a branch under a reserved
prefix, and a branch can be deleted. The default branch is never a target, the
push is fast-forward only onto a namespace nothing else uses, and no proposal
leaves without an explicit confirmation from the operator -- the same shape
`ApplyService` already uses for writing to a source tree.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# A credential-shaped assignment: the same shape the guardrail redacts.
# No leading \b: a credential key is usually prefixed -- DB_PASSWORD, MYSQL_
# ROOT_PASSWORD -- and `\bpassword` matches none of them, because `_` and `P`
# are both word characters. Over-matching is the safe direction here.
_CREDENTIAL = re.compile(
    r"(?i)[A-Za-z0-9_.-]*(api[_-]?key|token|password|secret|pwd)"
    r"\s*[=:]\s*(?P<value>[^\s,;]*)"
)
# Values these artefacts are supposed to carry. A .env.example whose password
# reads `change-me` is the point of the file, not a leak.
_PLACEHOLDERS = frozenset({"", '""', "''", "change-me", "changeme", "changeit", "..."})

BRANCH_NAMESPACE = "aset/"
# Deliberately strict: a branch name reaches a command line and a remote ref.
_BRANCH = re.compile(r"^aset/[a-z0-9][a-z0-9._-]{0,80}$")
_PROTECTED = frozenset({"main", "master", "head", "trunk", "develop"})
_GIT_TIMEOUT_SECONDS = 300


class DeliveryRefused(RuntimeError):
    """A proposal was not sent, and why."""


@dataclass(frozen=True)
class Proposal:
    """What a run offers back to a repository."""

    branch: str
    title: str
    body: str
    files: dict[str, str]
    """Files to create. Delivery refuses if one of these already exists."""
    run_id: str
    extends: dict[str, str] = field(default_factory=dict)
    """Files to append to, or create when absent.

    The distinction is not a convenience. The first pull request this system
    opened replaced a project's `.env.example` wholesale and deleted the
    documentation for a secret that file said had no default and failed at
    startup without. Adding to a file and replacing it are different acts, and
    nothing here should be able to do the second by accident."""


def clone_repository(url: str, destination: Path) -> Path:
    """Clone a repository to be worked on.

    This is the run copy with a different source: the agents still work on a copy
    and the original is untouched, exactly as `create_run_copy` arranges for a
    local directory.
    """
    destination = Path(destination)
    completed = subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", url, str(destination)],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS, check=False,
    )
    if completed.returncode != 0:
        raise DeliveryRefused(f"clone failed: {completed.stderr.strip()[-300:]}")
    return destination


class GitDelivery:
    """Puts a proposal on its own branch and pushes it.

    Only git. Opening the pull request is a separate step against a separate
    tool, so everything up to and including the push can be exercised against a
    repository on disk without anything reaching a hosting provider.
    """

    def __init__(self, *, git: str = "git") -> None:
        self.git = git

    def push(self, repository: Path, proposal: Proposal, *, confirmed: bool) -> str:
        """Write, commit and push a proposal. Returns the branch it created."""
        if not confirmed:
            raise DeliveryRefused(
                "delivery requires an explicit confirmation from the operator"
            )
        self._check_branch(proposal.branch)
        if not proposal.files and not proposal.extends:
            raise DeliveryRefused("a proposal with no files changes nothing")
        self._check_no_secret(proposal)
        created = self._resolve(repository, proposal.files, allow_missing_only=True)
        extended = self._resolve(repository, proposal.extends)

        # If this branch already exists on the remote, build on it. A second
        # delivery is then an ordinary commit and an ordinary fast-forward push,
        # which is why nothing here ever needs --force: a tool that writes into
        # someone else's repository should not be able to discard history at all.
        tracking = f"refs/remotes/origin/{proposal.branch}"
        subprocess.run(
            [self.git, "-C", str(repository), "fetch", "--quiet", "origin",
             f"+refs/heads/{proposal.branch}:{tracking}"],
            capture_output=True, timeout=_GIT_TIMEOUT_SECONDS, check=False,
        )
        existing = subprocess.run(
            [self.git, "-C", str(repository), "rev-parse", "--verify", "--quiet", tracking],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS, check=False,
        )
        if existing.returncode == 0:
            self._git(repository, "checkout", "-B", proposal.branch, tracking)
        else:
            self._git(repository, "checkout", "-B", proposal.branch)

        for name, (path, content) in zip(
            proposal.files, zip(created, proposal.files.values(), strict=True), strict=True
        ):
            # Against the base branch, not the working tree: a second delivery to
            # the same branch legitimately rewrites the file the first one added.
            # What must never be replaced is a file the project already had.
            if self._exists_in_base(repository, name):
                raise DeliveryRefused(
                    f"{name} already exists in the project; "
                    "propose an extension, not a replacement"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for path, content in zip(extended, proposal.extends.values(), strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if content.strip() and content.strip() in existing:
                continue
            separator = "" if not existing or existing.endswith("\n") else "\n"
            path.write_text(existing + separator + content, encoding="utf-8")
        self._git(
            repository, "add", "--", *(str(p) for p in (*created, *extended))
        )
        self._git(
            repository, "-c", "user.name=ASET",
            "-c", "user.email=aset@localhost.invalid",
            "commit", "--quiet", "--allow-empty", "-m", self._message(proposal),
        )
        self._git(
            repository, "push", "origin", f"{proposal.branch}:{proposal.branch}"
        )
        return proposal.branch

    # -- refusals ----------------------------------------------------------

    @staticmethod
    def _check_branch(branch: str) -> None:
        if branch.lower().strip("/") in _PROTECTED or "/" not in branch:
            raise DeliveryRefused(f"refusing to target the branch {branch!r}")
        if not branch.startswith(BRANCH_NAMESPACE):
            raise DeliveryRefused(
                f"a delivery branch must live under {BRANCH_NAMESPACE!r}"
            )
        if not _BRANCH.match(branch) or ".." in branch:
            raise DeliveryRefused(f"unusable branch name: {branch!r}")

    @staticmethod
    def _check_no_secret(proposal: Proposal) -> None:
        """Refuse rather than redact.

        A pull request body is durable and, on a public repository, public. A
        redacted body would still be published, and a placeholder standing where
        a credential was is not something to propose to someone silently.

        Only assignments with a real value count. `POSTGRES_PASSWORD: ${VAR}` and
        `DB_PASSWORD=change-me` are what these artefacts are *for*, and a check
        that refused them would refuse the delivery it exists to protect.

        This sees credential-shaped assignments and nothing else. A bare key in
        prose passes, which is a limit of the guardrail rather than a claim that
        the proposal is clean.
        """
        for label, text in (
            ("title", proposal.title),
            ("body", proposal.body),
            *(
                (f"file {name}", content)
                for name, content in (*proposal.files.items(), *proposal.extends.items())
            ),
        ):
            for match in _CREDENTIAL.finditer(text):
                value = match.group("value").strip().strip("\"'")
                if value.startswith("${") or value.lower() in _PLACEHOLDERS:
                    continue
                raise DeliveryRefused(
                    f"refusing to publish a secret in the {label}"
                )

    @staticmethod
    def _resolve(
        repository: Path, files: dict[str, str], *, allow_missing_only: bool = False
    ) -> list[Path]:
        root = Path(repository).resolve()
        resolved: list[Path] = []
        for name in files:
            candidate = (root / name).resolve()
            if candidate == root or root not in candidate.parents:
                raise DeliveryRefused(f"path is outside the repository: {name}")
            resolved.append(candidate)
        return resolved

    # -- plumbing ----------------------------------------------------------

    @staticmethod
    def _message(proposal: Proposal) -> str:
        return (
            f"{proposal.title}\n\n"
            f"{proposal.body}\n\n"
            f"Generated by ASET, run {proposal.run_id}.\n"
        )

    def _exists_in_base(self, repository: Path, name: str) -> bool:
        """Whether the project already tracks this path on its default branch."""
        # Only remote refs. HEAD is our own delivery branch once the first
        # commit lands, and asking it would report our own file as the
        # project's, refusing every update after the first.
        for reference in ("origin/HEAD", "origin/main", "origin/master"):
            found = subprocess.run(
                [self.git, "-C", str(repository), "cat-file", "-e", f"{reference}:{name}"],
                capture_output=True, timeout=_GIT_TIMEOUT_SECONDS, check=False,
            )
            if found.returncode == 0:
                return True
        return False

    def _git(self, repository: Path, *arguments: str) -> str:
        completed = subprocess.run(
            [self.git, "-C", str(repository), *arguments],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS, check=False,
        )
        if completed.returncode != 0:
            raise DeliveryRefused(
                f"git {arguments[0]} failed: {completed.stderr.strip()[-300:]}"
            )
        return completed.stdout


class GitHubPullRequests:
    """Opens the pull request, once the branch is already pushed.

    Separate from the push on purpose: everything up to and including the branch
    can be exercised against a repository on disk, and only this step needs an
    account. The base is never taken from the proposal -- it is read from the
    repository -- so a proposal cannot choose what it is merged into.
    """

    def __init__(self, *, runtime: str = "gh") -> None:
        self.runtime = runtime

    def open(
        self, repository: Path, proposal: Proposal, *, confirmed: bool
    ) -> str:
        if not confirmed:
            raise DeliveryRefused(
                "opening a pull request requires an explicit confirmation"
            )
        GitDelivery._check_branch(proposal.branch)
        GitDelivery._check_no_secret(proposal)
        base = self._default_branch(repository)
        if proposal.branch == base:
            raise DeliveryRefused("a branch cannot be a pull request against itself")
        completed = subprocess.run(
            [
                self.runtime, "pr", "create",
                "--head", proposal.branch,
                "--base", base,
                "--title", proposal.title,
                "--body", self._body(proposal),
            ],
            cwd=repository, capture_output=True, text=True,
            timeout=_GIT_TIMEOUT_SECONDS, check=False,
        )
        if completed.returncode != 0:
            raise DeliveryRefused(
                f"pull request was not opened: {completed.stderr.strip()[-300:]}"
            )
        return completed.stdout.strip().splitlines()[-1]

    def _default_branch(self, repository: Path) -> str:
        completed = subprocess.run(
            [self.runtime, "repo", "view", "--json", "defaultBranchRef",
             "--jq", ".defaultBranchRef.name"],
            cwd=repository, capture_output=True, text=True,
            timeout=_GIT_TIMEOUT_SECONDS, check=False,
        )
        base = completed.stdout.strip()
        if completed.returncode != 0 or not base:
            raise DeliveryRefused("could not determine the repository's base branch")
        return base

    @staticmethod
    def _body(proposal: Proposal) -> str:
        """Always says what made it.

        A pull request that hides its origin is a worse artefact and a worse
        position for whoever's account opened it.
        """
        return (
            f"{proposal.body}\n\n"
            "---\n\n"
            f"Opened by ASET from run `{proposal.run_id}`. Every file in this "
            "branch was generated; nothing in the project was edited by hand. "
            "The branch lives under `aset/` and can be deleted without trace.\n"
        )


def infrastructure_proposal(
    compose: str,
    env_example: str,
    *,
    run_id: str,
    engines: tuple[str, ...],
    read_from: tuple[str, ...] = (),
) -> Proposal | None:
    """Turn a derived topology into something a person can review.

    The first thing this system offers back, and deliberately the safest: it adds
    two files and edits none, so the worst case is a branch nobody merges. A
    project that needs no services produces no proposal, which is the right
    answer rather than an empty pull request.
    """
    if not compose.strip() or not engines:
        return None
    unique = tuple(dict.fromkeys(engines))
    named = (
        unique[0] if len(unique) == 1
        else " and ".join((", ".join(unique[:-1]), unique[-1]))
    )
    sources = "\n".join(f"- `{name}`" for name in read_from)
    body = (
        f"This project's tests expect {named} to already be running. There is no "
        "compose file here, so getting it running means reading the README and "
        "installing services by hand.\n\n"
        "These two files were derived from the connection strings the project "
        "already declares"
        + (f", read from:\n\n{sources}\n" if read_from else ".\n")
        + "\nWith them, `docker compose up -d` gives the tests what they expect at "
        "the addresses the existing configuration already points to. No "
        "application code changes.\n\n"
        "**What was assumed.** Engine versions: nothing in the configuration "
        "states one, so a current release was chosen and pinned by digest. Change "
        "it if the project targets something else.\n\n"
        "**Credentials** are read from the environment, with `.env.example` as "
        "the template. Nothing secret is committed here."
    )
    return Proposal(
        branch=f"aset/compose-{'-'.join(unique)}",
        title=f"Add a compose file for local development ({named})",
        body=body,
        files={"docker-compose.yml": compose},
        run_id=run_id,
        # A project usually has one already, documenting more than a database.
        extends={".env.example": env_example},
    )


class GitHubMCPPullRequests:
    """Opens the pull request through the GitHub MCP server.

    Same port as `GitHubPullRequests`, a different way of reaching GitHub: the
    server runs as a container over stdio, which is the transport this project
    already uses for its own MCP ports. The refusals are shared, not
    reimplemented -- a second backend must not become a second policy.
    """

    def __init__(
        self,
        *,
        image: str = "ghcr.io/github/github-mcp-server:latest",
        token: str = "",
        runtime: str = "docker",
    ) -> None:
        self.image = image
        self.token = token
        self.runtime = runtime

    def server_command(self) -> list[str]:
        """The argv that starts the server. The token is passed by name only.

        `-e NAME` without a value tells the runtime to forward the variable from
        the environment, so the secret never appears in a command line where a
        process listing would show it.
        """
        return [
            self.runtime, "run", "-i", "--rm",
            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
            self.image, "stdio",
        ]

    def open(self, repository: Path, proposal: Proposal, *, confirmed: bool) -> str:
        if not confirmed:
            raise DeliveryRefused(
                "opening a pull request requires an explicit confirmation"
            )
        if not self.token:
            raise DeliveryRefused("no GitHub token is configured for delivery")
        GitDelivery._check_branch(proposal.branch)
        GitDelivery._check_no_secret(proposal)
        raise DeliveryRefused(
            "the MCP delivery backend is configured but not yet implemented; "
            "use the gh backend, which is verified"
        )


def build_delivery(settings) -> object | None:
    """Pick the delivery backend named by configuration, or refuse to guess.

    Returns None when delivery is off, which is the default. There is no
    fallback between backends: a run that cannot deliver the way it was
    configured must say so rather than quietly using the other one.
    """
    choice = getattr(settings, "delivery_backend", "none")
    if choice == "none":
        return None
    if choice == "gh":
        return GitHubPullRequests()
    if choice == "mcp":
        secret = getattr(settings, "github_personal_access_token", None)
        token = secret.get_secret_value() if secret is not None else ""
        if not token:
            raise DeliveryRefused(
                "delivery_backend is 'mcp' but no GitHub token is configured"
            )
        return GitHubMCPPullRequests(
            image=settings.github_mcp_image, token=token
        )
    raise DeliveryRefused(f"unknown delivery_backend: {choice!r}")
