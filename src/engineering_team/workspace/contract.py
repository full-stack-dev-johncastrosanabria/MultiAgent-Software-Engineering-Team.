"""Where the project's files live, named as a contract instead of assumed.

[ADR 17](../../../docs/architecture/decisions/0017-the-project-lives-in-the-run.md)
decides that the project should live in a run-scoped volume rather than on the
operator's disk, and says why that cannot be done by changing a path:
`RepositoryMCP` was bound to the host filesystem by construction. What the change
needs first is this contract -- read a file, write a file, list, search -- with
the host directory as one implementation and the volume as the other. It is the
twin of what [ADR 3](../../../docs/architecture/decisions/0003-split-quality-mcp.md)
did for `CommandRunner`, and naming the contract is what makes the rest
mechanical.

What lives here is mechanism. Which roles may read or write, what counts as a
change and how a diff is rendered stay in `RepositoryMCP`: a workspace that
decided policy would have to be re-audited once per implementation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Protocol, Self, runtime_checkable

# Never architectural evidence, and they dominate the tree by volume. `.git`
# additionally holds credentials: its remotes can carry them in the URL.
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
})

# The path every container mounts the project at (ADR 15), and the path a
# volume-backed workspace works from.
PROJECT_MOUNT = PurePosixPath("/aset/project-root")


def is_secret_path(path: str | Path) -> bool:
    return any(
        part == ".env" or part.startswith(".env.") for part in Path(path).parts
    )


def is_excluded(relative: str | Path) -> bool:
    return any(part in EXCLUDED_DIRECTORIES for part in Path(relative).parts)


def refuse_traversal(relative: str) -> PurePosixPath:
    """The one check both implementations owe their caller before touching IO."""
    requested = Path(relative)
    if requested.is_absolute() or ".." in requested.parts or is_secret_path(requested):
        raise ValueError("path traversal denied")
    return PurePosixPath(requested.as_posix())


@runtime_checkable
class Workspace(Protocol):
    """The project's files, wherever they live."""

    def list_paths(self) -> list[Path]:
        """Every path an agent may see, relative to the project root."""

    def read(self, relative: str) -> str:
        """The contents of one file. Raises for anything outside the project."""

    def write(self, relative: str, content: str) -> None:
        """Replace one file's contents, creating parents as needed."""

    def exists(self, relative: str) -> bool:
        """Whether one path is a readable file."""

    def search(self, query: str) -> list[Path]:
        """Every visible file whose contents contain `query`, case-folded."""


def _git_visible_paths(root: Path) -> list[str] | None:
    """What git would show: tracked plus untracked, minus everything ignored.

    Delegating to git gives .gitignore's exact semantics -- nested files and
    negated patterns included -- without reimplementing it, and avoids walking
    the trees the project itself already declared disposable.
    """
    try:
        completed = subprocess.run(
            [
                "git", "-C", str(root), "ls-files",
                "--cached", "--others", "--exclude-standard", "-z",
            ],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    decoded = completed.stdout.decode("utf-8", "replace")
    return [entry for entry in decoded.split("\0") if entry]


class HostWorkspace:
    """The project on the operator's disk. What ASET does today.

    `create_run_copy` still produces the directory this reads, and ADR 17 is
    explicit that it stays until the volume path is measured: a direction is not
    a migration.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def path(self, relative: str) -> Path:
        target = (self.root / str(refuse_traversal(relative))).resolve()
        if self.root not in target.parents and target != self.root:
            raise ValueError("outside workspace denied")
        return target

    def _candidates(self):
        tracked = _git_visible_paths(self.root)
        if tracked is not None:
            for entry in tracked:
                yield Path(entry)
            return
        # Without a git repo there are no declared exclusions to consult, but
        # pruning the heavy directories avoids walking them, not merely omitting
        # them from the result.
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in EXCLUDED_DIRECTORIES:
                        stack.append(entry)
                    continue
                try:
                    yield entry.relative_to(self.root)
                except ValueError:
                    continue

    def files(self):
        """Every visible file as `(absolute, relative)`."""
        for relative in self._candidates():
            if is_excluded(relative) or is_secret_path(relative):
                continue
            path = self.root / relative
            try:
                resolved = path.resolve()
                if (
                    path.is_symlink()
                    or not resolved.is_file()
                    or (resolved != self.root and self.root not in resolved.parents)
                ):
                    continue
                yield path, relative
            except OSError:
                continue

    def list_paths(self) -> list[Path]:
        return [relative for _, relative in self.files()]

    def read(self, relative: str) -> str:
        return self.path(relative).read_text(encoding="utf-8")

    def write(self, relative: str, content: str) -> None:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def exists(self, relative: str) -> bool:
        try:
            return self.path(relative).exists()
        except ValueError:
            return False

    def search(self, query: str) -> list[Path]:
        folded = query.casefold()
        found: list[Path] = []
        for path, relative in self.files():
            try:
                if folded in path.read_text(encoding="utf-8", errors="ignore").casefold():
                    found.append(relative)
            except OSError:
                continue
        return found


class WorkspaceError(OSError):
    """The workspace could not answer. Kept an OSError so callers need no new arm."""


class VolumeWorkspace:
    """The project inside a run-scoped named volume, reached one container at a time.

    Nothing about the target project touches the operator's disk: the volume is
    created by the run, populated by a container, mounted at `/aset/project-root`
    by every container that works on it, and removed when the run ends. Each
    operation here is its own short-lived container for the same reason
    [ADR 15](../../../docs/architecture/decisions/0015-container-only.md) gives
    for commands -- a long-lived container would have to be given a network and
    a lifetime that outlive the operation.

    It carries ADR 16's labels, and it is deliberately unoptimised: correctness
    first, and ADR 17 requires the volume path to be *measured* before it
    replaces the host copy, not assumed faster.
    """

    def __init__(
        self,
        volume: str,
        *,
        image: str,
        runtime: str = "docker",
        run_id: str = "",
        project: str = "",
    ) -> None:
        self.volume = volume
        self.image = image
        self.runtime = runtime
        self.run_id = run_id
        self.project = project
        self._created = False

    # -- lifecycle ---------------------------------------------------------

    def _labels(self) -> list[str]:
        from engineering_team.docker_labels import label_arguments

        return label_arguments(self.run_id, self.project)

    def up(self) -> Self:
        completed = self._runtime_call(
            ["volume", "create", *self._labels(), self.volume]
        )
        if completed.returncode != 0:
            raise WorkspaceError(f"workspace volume was not created: {self.volume}")
        self._created = True
        return self

    def down(self) -> None:
        """Remove the volume. Build output created inside it dies with it."""
        if not self._created:
            return
        self._runtime_call(["volume", "rm", "--force", self.volume])
        self._created = False

    def __enter__(self) -> Self:
        return self.up()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.down()

    # -- population --------------------------------------------------------

    def populate_from_host(self, source: str | Path) -> None:
        """Copy a host directory in, for the case where there is nothing to clone."""
        source_path = Path(source).resolve()
        if not source_path.is_dir():
            raise WorkspaceError(f"source workspace does not exist: {source}")
        completed = self._runtime_call([
            "run", "--rm", *self._labels(),
            "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={source_path},target=/aset/source,readonly",
            "--mount", f"type=volume,source={self.volume},target={PROJECT_MOUNT}",
            self.image,
            "sh", "-c",
            f"cp -a /aset/source/. {PROJECT_MOUNT}/",
        ])
        if completed.returncode != 0:
            raise WorkspaceError(f"workspace was not populated: {completed.stderr[-500:]}")

    def clone(self, url: str, *, token: str = "", depth: int = 1) -> None:
        """Clone the project into the volume. The one container that gets a token.

        ADR 17 states this as an exception rather than letting it look like the
        rule: the token reaches the clone container and nothing else. It is not
        written into the volume, it is not in any quality container's
        environment, and the container is removed when the clone ends. Every
        other container in the run keeps the egress it has today, which is none.

        The clone is shallow. `git log` and `git blame` therefore see nothing, so
        no agent may reason from history; what delivery needs is a branch and a
        diff (ADR 6), and a shallow clone provides both.
        """
        arguments = [
            "run", "--rm", *self._labels(),
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--mount", f"type=volume,source={self.volume},target={PROJECT_MOUNT}",
        ]
        if token:
            # Through the environment, never the command line: argv is readable
            # from outside the container, and a URL carrying a token would also
            # be written into .git/config inside the volume.
            arguments += ["--env", "ASET_CLONE_TOKEN"]
        arguments += [
            self.image, "sh", "-c",
            ('set -e; url="$1"; '
             'if [ -n "${ASET_CLONE_TOKEN:-}" ]; then '
             '  url=$(printf "%s" "$url" | sed "s#https://#https://x-access-token:'
             '${ASET_CLONE_TOKEN}@#"); fi; '
             f'git clone --quiet --depth {int(depth)} "$url" {PROJECT_MOUNT}; '
             f'git -C {PROJECT_MOUNT} remote set-url origin "$2"'),
            "sh", url, url,
        ]
        environment = dict(os.environ)
        if token:
            environment["ASET_CLONE_TOKEN"] = token
        completed = self._runtime_call(arguments, environment=environment)
        if completed.returncode != 0:
            raise WorkspaceError("clone into the run workspace failed")

    # -- extraction --------------------------------------------------------

    def extract(self, destination: str | Path, *relatives: str) -> list[Path]:
        """Copy named files out to the host before the volume is destroyed.

        ADR 17 is explicit that removing the volume without this is worse than
        what exists today: an operator can read `workspace/runs/<run_id>` after a
        failed run, and a volume that dies with the run takes that away. So
        whatever is worth keeping -- the diff, the logs, the evidence -- is
        extracted deliberately, by name, while the volume still exists. Nothing
        is extracted implicitly: a teardown that quietly copied the tree back to
        disk would reintroduce the accumulation ADR 17 removes.
        """
        target = Path(destination).resolve()
        target.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for relative in relatives:
            inside = refuse_traversal(relative)
            completed = self._in_container(["cat", "--", str(inside)])
            if completed.returncode != 0:
                continue
            path = target / str(inside)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(completed.stdout, encoding="utf-8")
            written.append(Path(str(inside)))
        return written

    # -- contract ----------------------------------------------------------

    def list_paths(self) -> list[Path]:
        completed = self._in_container([
            "sh", "-c",
            ("git ls-files --cached --others --exclude-standard -z 2>/dev/null "
             "|| find . -type f -print0"),
        ])
        if completed.returncode != 0:
            return []
        entries = [item for item in completed.stdout.split("\0") if item]
        visible = []
        for entry in entries:
            relative = Path(entry.removeprefix("./"))
            if is_excluded(relative) or is_secret_path(relative):
                continue
            visible.append(relative)
        return visible

    def read(self, relative: str) -> str:
        inside = refuse_traversal(relative)
        completed = self._in_container(["cat", "--", str(inside)])
        if completed.returncode != 0:
            raise WorkspaceError(f"file not found: {relative}")
        return completed.stdout

    def write(self, relative: str, content: str) -> None:
        inside = refuse_traversal(relative)
        completed = self._in_container(
            ["sh", "-c", 'mkdir -p "$(dirname "$1")" && cat > "$1"', "sh", str(inside)],
            stdin=content,
        )
        if completed.returncode != 0:
            raise WorkspaceError(f"file was not written: {relative}")

    def exists(self, relative: str) -> bool:
        try:
            inside = refuse_traversal(relative)
        except ValueError:
            return False
        return self._in_container(["test", "-f", str(inside)]).returncode == 0

    def search(self, query: str) -> list[Path]:
        completed = self._in_container(
            ["grep", "-rilF", "--", query, "."],
        )
        if completed.returncode not in (0, 1):
            return []
        found = []
        for line in completed.stdout.splitlines():
            entry = line.strip()
            if not entry:
                continue
            relative = Path(entry.removeprefix("./"))
            if is_excluded(relative) or is_secret_path(relative):
                continue
            found.append(relative)
        return found

    # -- plumbing ----------------------------------------------------------

    def _in_container(self, command: list[str], *, stdin: str | None = None):
        return self._runtime_call(
            [
                "run", "--rm", "--interactive" if stdin is not None else "--attach=stdout",
                *self._labels(),
                "--network", "none", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--mount", f"type=volume,source={self.volume},target={PROJECT_MOUNT}",
                "--workdir", str(PROJECT_MOUNT),
                self.image, *command,
            ],
            stdin=stdin,
        )

    def _runtime_call(self, arguments: list[str], *, stdin: str | None = None,
                      environment: dict[str, str] | None = None):
        try:
            return subprocess.run(
                [self.runtime, *arguments],
                input=stdin, capture_output=True, text=True,
                timeout=600, check=False, env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkspaceError(str(exc)) from exc
