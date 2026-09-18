"""What every runner agrees on, independent of the boundary it enforces.

A command, the protocol that runs one, and the two small utilities a backend
needs. This module knows nothing about how a boundary is enforced. It was
extracted while there were two backends so the contract would outlive either;
`ContainerRunner` is the only one left (ADR 15), and the contract still does
not name it.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

_OUTPUT_LIMIT = 4096
_STRUCTURED_OUTPUT_LIMIT = 4 * 1024 * 1024
# A separate, generous budget for the *earliest* bytes of an ordinary (not
# structured-output) stream, captured once as they stream past and kept
# alongside -- not instead of -- the tail `_OUTPUT_LIMIT` already keeps. This
# module still knows nothing about what those bytes mean; it only agrees to
# remember more than one window of them. Sized well past the download-noise
# a real, verbose build phase produces before its own failure detail
# (observed: ~9.6 KB in a representative fixture) so that detail commonly
# reaches whichever caller reads a stream's start, without approaching
# `_STRUCTURED_OUTPUT_LIMIT`, which stays reserved for the dependency-scan
# path this budget is never applied to.
_HEAD_RETENTION_LIMIT = 64 * 1024
# Marks a genuine gap between a stream's retained head and its retained tail --
# never printed when the two windows already meet or overlap, because then
# nothing was actually lost. See `_BoundedOutput.head_text`.
_STREAM_GAP_MARKER = "\n...[stream truncated]...\n"


def _remaining(deadline: float) -> float:
    """Seconds left before the deadline, never negative."""
    return max(0.0, deadline - time.monotonic())


class _BoundedOutput:
    def __init__(self, limit: int = _OUTPUT_LIMIT, *, keep_head: int = 0) -> None:
        self._limit = limit
        self._buffer = bytearray()
        # Captured once, independently of the tail: the tail keeps sliding as
        # more arrives, so without a separate copy the earliest bytes of any
        # stream longer than `limit` are gone by the time a caller can ask for
        # them -- which is exactly the case a build long enough to need
        # truncation at all is in.
        self._head = bytearray()
        self._head_limit = keep_head
        # Total bytes ever appended, independent of how much either window
        # currently retains. `head_text` needs this to tell "the tail's window
        # starts inside what the head already captured" (no bytes missing)
        # apart from "the tail's window starts past where the head stopped"
        # (a real gap) -- a distinction neither window's own length exposes
        # once the head has stopped growing at `keep_head`.
        self._total = 0
        self.truncated = False
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self._lock:
            if len(self._head) < self._head_limit:
                self._head.extend(chunk[: self._head_limit - len(self._head)])
            self._buffer.extend(chunk)
            self._total += len(chunk)
            if len(self._buffer) > self._limit:
                self.truncated = True
                del self._buffer[:-self._limit]

    def text(self) -> str:
        with self._lock:
            return bytes(self._buffer).decode("utf-8", errors="replace")

    def head_text(self) -> str:
        """The stream's earliest bytes not already covered by `text()`'s tail.

        Ready to prepend directly ahead of `text()`: concatenating the two
        reconstructs the original stream. "" when there is nothing to add --
        `keep_head` was never requested, or the stream never grew past what
        the tail alone already retains.

        Otherwise trimmed to end exactly where the tail's own window begins,
        so a stream short enough to fit entirely inside `keep_head` (routine:
        `keep_head` is sized generously past `limit`) reconstructs with the
        tail's bytes appearing once, not twice. A gap marker is appended only
        when the head actually stopped -- at `keep_head` -- before reaching
        where the tail begins; when the two windows meet or overlap instead,
        nothing was lost and no marker is printed.
        """
        with self._lock:
            if not self.truncated or not self._head_limit:
                return ""
            tail_start = self._total - self._limit  # > 0: `truncated` implies this
            head_end = len(self._head)  # == min(self._total, self._head_limit)
            prefix = bytes(self._head[: min(head_end, tail_start)]).decode(
                "utf-8", errors="replace"
            )
            if not prefix:
                return ""
            return prefix if head_end >= tail_start else prefix + _STREAM_GAP_MARKER


class CommandOutput(subprocess.CompletedProcess[str]):
    """A bounded result that explicitly marks incomplete output evidence."""

    def __init__(
        self, args: list[str], returncode: int, stdout: str, stderr: str,
        *, output_truncated: bool = False, stdout_head: str = "", stderr_head: str = "",
    ) -> None:
        super().__init__(args, returncode, stdout, stderr)
        self.output_truncated = output_truncated
        # "" unless the runner requested head retention and a stream actually
        # grew past its tail budget -- see `_BoundedOutput.head_text`. A caller
        # that never asked for this (every dependency-scan/structured-output
        # command) sees the same two empty strings it always did.
        self.stdout_head = stdout_head
        self.stderr_head = stderr_head


@dataclass(frozen=True)
class CommandRequest:
    """One command to execute under a runner's boundary."""

    args: tuple[str, ...]
    cwd: Path
    deadline: float
    allow_network: bool = False
    env: tuple[tuple[str, str], ...] = ()
    """Extra environment the command needs, as explicit pairs.

    Some toolchains are only configurable this way: the .NET CLI decides where to
    write its first-run state from DOTNET_CLI_HOME, and there is no argument for
    it. Kept to declared pairs rather than inheriting the operator's environment,
    which is the whole reason PATH is rebuilt rather than passed through.
    """
    writable_paths: tuple[str, ...] = ()
    """Host paths outside the boundary that this toolchain has to write to.

    Declared by the stack profile, never by the caller: a fixed path a runtime
    will not be talked out of is a property of the toolchain, and granting it
    here keeps the grant narrow instead of opening the directory it sits in.
    """
    allow_subprocesses: bool = False
    """Whether the command may fork.

    A process sandbox has to police this from outside the kernel namespace it is
    protecting, which is what makes it a race. A container backend can ignore the
    flag: the container's lifecycle already bounds every descendant.
    """

    structured_output: bool = False
    """Retain up to 4 MiB per stream for machine-readable scanner evidence.

    Ordinary commands retain their 4 KiB diagnostic tails. Even this opt-in is
    bounded; a runner must mark truncated evidence so consumers can fail closed.
    """


@runtime_checkable
class CommandRunner(Protocol):
    """Runs a command under some boundary and reports what it produced."""

    environment: Path | None
    """Writable directory the boundary must grant, once the owner has created it."""

    def require_available(self, deadline: float | None = None) -> None:
        """Raise if this runner cannot enforce its boundary on this host.

        Asked before any work is prepared, so an unsupported host fails before a
        command is built rather than after one has already run unprotected.

        `deadline`, when given, bounds how long this may spend probing an
        external dependency (a container runtime's daemon, say) -- a runner
        with nothing to probe can ignore it.
        """
        ...

    @property
    def closing(self) -> bool:
        """Whether this runner is shutting down and must accept no new work."""
        ...

    def prepare_environment(self, deadline: float) -> str:
        """Provision the toolchain this runner will execute against.

        Returns the interpreter path in whatever namespace the runner works in:
        a host path for a process sandbox, a container path for a container. The
        caller treats it as opaque and hands it back through `execute`.
        """
        ...

    def execute(self, request: CommandRequest) -> subprocess.CompletedProcess[str]:
        ...

    def close(self) -> None:
        ...
