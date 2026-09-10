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


def _remaining(deadline: float) -> float:
    """Seconds left before the deadline, never negative."""
    return max(0.0, deadline - time.monotonic())


class _BoundedOutput:
    def __init__(self, limit: int = _OUTPUT_LIMIT) -> None:
        self._limit = limit
        self._buffer = bytearray()
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self._lock:
            self._buffer.extend(chunk)
            if len(self._buffer) > self._limit:
                del self._buffer[:-self._limit]

    def text(self) -> str:
        with self._lock:
            return bytes(self._buffer).decode("utf-8", errors="replace")


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


@runtime_checkable
class CommandRunner(Protocol):
    """Runs a command under some boundary and reports what it produced."""

    environment: Path | None
    """Writable directory the boundary must grant, once the owner has created it."""

    def require_available(self) -> None:
        """Raise if this runner cannot enforce its boundary on this host.

        Asked before any work is prepared, so an unsupported host fails before a
        command is built rather than after one has already run unprotected.
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
