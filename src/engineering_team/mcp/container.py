"""A runner whose boundary is a container rather than a process sandbox.

See `docs/architecture/decisions/0002-container-runner.md`. The short version:
supervising processes that share the host kernel from userspace is a race this
project kept losing, and a process sandbox cannot supply the toolchain a target
project needs. A container bounds its own descendants and carries its own
toolchain, so both problems stop being this code's problem.

Each command runs as its own short-lived container. That makes network access a
per-command decision rather than a property of a long-lived container that would
have to be attached and detached while work is in flight. State that must survive
between commands -- the ephemeral environment a project's dependencies install
into -- lives on a volume that every container in the run mounts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from engineering_team.mcp.runner import (
    _OUTPUT_LIMIT,
    CommandRequest,
    _BoundedOutput,
    _remaining,
)

WORKSPACE_MOUNT = PurePosixPath("/aset/workspace")
ENVIRONMENT_MOUNT = PurePosixPath("/aset/env")

_DIGEST_PINNED = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_KILL_GRACE_SECONDS = 10.0


@dataclass(frozen=True)
class ContainerLimits:
    """What a single command may consume before the runtime stops it."""

    memory: str = "2g"
    cpus: str = "2"
    pids: int = 512


class ContainerRunner:
    """Runs each command in its own container.

    `allow_subprocesses` is accepted and ignored. A process sandbox has to police
    forking from outside the namespace it protects, which is what made it a race;
    a container's lifecycle already bounds every descendant, so the question does
    not arise.
    """

    def __init__(
        self,
        workspace: Path,
        *,
        image: str,
        runtime: str = "docker",
        limits: ContainerLimits | None = None,
        allow_unpinned_image: bool = False,
        network: str | None = None,
    ) -> None:
        if not allow_unpinned_image and not _DIGEST_PINNED.match(image):
            raise ValueError(
                "container image must be pinned by digest (name@sha256:...); "
                "pass allow_unpinned_image=True only for local experiments"
            )
        self.workspace = workspace
        # The volume is mounted at a fixed path by every container this runner
        # starts, so the environment root exists before anything provisions into
        # it. Toolchains that keep a cache need somewhere to put it from the very
        # first command, not only after a Python interpreter has been built.
        self.environment: Path | None = Path(ENVIRONMENT_MOUNT)
        self.image = image
        self.runtime = runtime
        self.limits = limits or ContainerLimits()
        # The run's service network, when the project declares dependencies. It
        # is internal, so a command that also needs the registry is attached to
        # the default bridge as well -- see _run_container.
        self.network = network
        self._token = uuid.uuid4().hex[:12]
        self._volume = f"aset-env-{self._token}"
        self._sequence = 0
        self._lock = threading.Lock()
        self._live_containers: set[str] = set()
        self._closing_event = threading.Event()
        self._volume_created = False

    # -- interface ---------------------------------------------------------

    def require_available(self) -> None:
        """Raise unless the runtime is installed and its daemon answers."""
        executable = shutil.which(self.runtime)
        if executable is None:
            raise RuntimeError(
                f"quality container runtime is unavailable: {self.runtime} not found"
            )
        try:
            probe = subprocess.run(
                [executable, "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                "quality container runtime is unavailable: daemon did not answer"
            ) from exc
        if probe.returncode != 0:
            raise RuntimeError(
                "quality container runtime is unavailable: daemon did not answer"
            )

    @property
    def closing(self) -> bool:
        return self._closing_event.is_set()

    def prepare_environment(self, deadline: float) -> str:
        """Build the interpreter inside the container, on the shared volume.

        The path returned is a container path. It survives between commands
        because every container in this run mounts the same volume at the same
        place, which is the only state that has to outlive a single command.

        This still assumes a Python image, because the quality layer above is
        still Python-shaped. Choosing the image and the commands per ecosystem is
        the stack-profile half of ADR 3, and is not done yet.
        """
        environment = ENVIRONMENT_MOUNT
        interpreter = str(environment / "bin" / "python")
        created = self.execute(
            CommandRequest(
                args=("python", "-I", "-m", "venv", "--without-pip", str(environment)),
                cwd=self.workspace,
                deadline=deadline,
            )
        )
        if created.returncode != 0:
            raise RuntimeError(
                f"venv creation failed in container: {created.stderr[-1000:]}"
            )
        completed = self.execute(
            CommandRequest(
                args=(interpreter, "-I", "-m", "ensurepip", "--upgrade"),
                cwd=self.workspace,
                deadline=deadline,
            )
        )
        if completed.returncode != 0:
            output = (completed.stdout + completed.stderr)[-1000:]
            raise RuntimeError(f"ensurepip failed in container: {output}")
        self.environment = Path(environment)
        return interpreter

    def execute(self, request: CommandRequest) -> subprocess.CompletedProcess[str]:
        if self._closing_event.is_set():
            raise RuntimeError("quality environment is closing")
        self._ensure_volume()
        name = self._reserve_name()
        args = self._container_command(name, request)
        try:
            return self._run_container(name, args, request)
        finally:
            with self._lock:
                self._live_containers.discard(name)

    def close(self) -> None:
        """Kill every container this runner started and drop its volume."""
        self._closing_event.set()
        with self._lock:
            live = tuple(self._live_containers)
        for name in live:
            self._quiet([self.runtime, "kill", name], timeout=_KILL_GRACE_SECONDS)
        if self._volume_created:
            self._quiet(
                [self.runtime, "volume", "rm", "--force", self._volume], timeout=30
            )
            self._volume_created = False

    # -- construction ------------------------------------------------------

    def _reserve_name(self) -> str:
        with self._lock:
            self._sequence += 1
            name = f"aset-{self._token}-{self._sequence}"
            self._live_containers.add(name)
        return name

    def _container_command(self, name: str, request: CommandRequest) -> list[str]:
        """Build the argv that starts one command inside its own container."""
        args = [
            self.runtime,
            # `create` and not `run`: a container can only be given one network at
            # start, and a command may need both the project's internal service
            # network and a route to the registry. Connecting the second one
            # requires the container to exist first.
            "create",
            "--rm",
            "--name",
            name,
            # The container is the boundary; nothing inside needs to raise
            # privilege, and nothing outside is reachable but the two mounts.
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--network",
            self._primary_network(request),
            "--memory",
            self.limits.memory,
            "--cpus",
            self.limits.cpus,
            "--pids-limit",
            str(self.limits.pids),
            "--mount",
            f"type=bind,source={self.workspace},target={WORKSPACE_MOUNT}",
            "--mount",
            f"type=volume,source={self._volume},target={ENVIRONMENT_MOUNT}",
            "--workdir",
            str(self._container_path(request.cwd)),
        ]
        # Without this the container writes into the bind mount as root and
        # leaves the run workspace owned by a user the host cannot clean up.
        if hasattr(os, "getuid"):
            args += ["--user", f"{os.getuid()}:{os.getgid()}"]
        for variable, value in request.env:
            args += ["--env", f"{variable}={value}"]
        args.append(self.image)
        args.extend(request.args)
        return args

    def _primary_network(self, request: CommandRequest) -> str:
        """The network the container starts on.

        The service network wins when there is one: reaching the project's
        database is not optional, and the route to the registry is added
        afterwards for the commands that need it.
        """
        if self.network:
            return self.network
        return "bridge" if request.allow_network else "none"

    def _needs_extra_route(self, request: CommandRequest) -> bool:
        """Whether a second, external network has to be attached after creation."""
        return bool(self.network) and request.allow_network

    def _container_path(self, path: Path) -> PurePosixPath:
        """Translate a host path under the workspace to its path in the container."""
        resolved = Path(path).resolve()
        workspace = Path(self.workspace).resolve()
        if resolved == workspace:
            return WORKSPACE_MOUNT
        try:
            relative = resolved.relative_to(workspace)
        except ValueError:
            raise ValueError(
                f"path is outside the mounted workspace: {path}"
            ) from None
        return WORKSPACE_MOUNT / PurePosixPath(*relative.parts)

    def _ensure_volume(self) -> None:
        if self._volume_created:
            return
        created = self._quiet(
            [self.runtime, "volume", "create", self._volume], timeout=60
        )
        if created is None or created.returncode != 0:
            raise RuntimeError("quality container environment volume was not created")
        self._volume_created = True
        self._hand_volume_to_the_unprivileged_user()

    def _hand_volume_to_the_unprivileged_user(self) -> None:
        """Give the run's volume to the user every other container runs as.

        A fresh named volume is owned by root, so the unprivileged user the real
        work runs as cannot create the environment inside it. This is the only
        container that runs as root, and it is granted exactly one capability,
        no network, and nothing but the volume it is about to hand over.
        """
        if not hasattr(os, "getuid"):
            return
        handed = self._quiet(
            [
                self.runtime, "run", "--rm",
                "--user", "0:0",
                "--network", "none",
                "--cap-drop", "ALL",
                "--cap-add", "CHOWN",
                "--security-opt", "no-new-privileges",
                "--mount",
                f"type=volume,source={self._volume},target={ENVIRONMENT_MOUNT}",
                self.image,
                "chown", f"{os.getuid()}:{os.getgid()}", str(ENVIRONMENT_MOUNT),
            ],
            timeout=120,
        )
        if handed is None or handed.returncode != 0:
            detail = "" if handed is None else handed.stderr[-500:]
            raise RuntimeError(
                f"quality container environment volume is not writable: {detail}"
            )

    # -- execution ---------------------------------------------------------

    def _run_container(
        self, name: str, args: list[str], request: CommandRequest
    ) -> subprocess.CompletedProcess[str]:
        timeout = _remaining(request.deadline)
        stdout_buffer = _BoundedOutput(_OUTPUT_LIMIT)
        stderr_buffer = _BoundedOutput(_OUTPUT_LIMIT)
        created = self._quiet(args, timeout=max(1.0, min(timeout, 120.0)))
        if created is None or created.returncode != 0:
            detail = "" if created is None else created.stderr.strip()[-400:]
            raise RuntimeError(f"container was not created: {detail}")
        if self._needs_extra_route(request):
            # The service network is internal by construction, so a command that
            # also resolves dependencies needs a second attachment.
            self._quiet([self.runtime, "network", "connect", "bridge", name], timeout=60)
        process = subprocess.Popen(
            [self.runtime, "start", "--attach", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        readers = tuple(
            threading.Thread(
                target=self._drain,
                args=(stream, buffer),
                name=f"container-output-{name}",
                daemon=True,
            )
            for stream, buffer in (
                (process.stdout, stdout_buffer),
                (process.stderr, stderr_buffer),
            )
        )
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Killing the container kills everything it contains. There is no
            # descendant to hunt and no PID to reuse.
            self._quiet([self.runtime, "kill", name], timeout=_KILL_GRACE_SECONDS)
            try:
                process.wait(timeout=_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_KILL_GRACE_SECONDS)
        finally:
            for reader in readers:
                reader.join(timeout=1.0)
        if timed_out:
            raise subprocess.TimeoutExpired(
                list(request.args),
                timeout,
                output=stdout_buffer.text(),
                stderr=stderr_buffer.text(),
            )
        return subprocess.CompletedProcess(
            list(request.args),
            process.returncode,
            stdout_buffer.text(),
            stderr_buffer.text(),
        )

    @staticmethod
    def _drain(stream, buffer: _BoundedOutput) -> None:
        try:
            for chunk in iter(lambda: stream.read(4096), b""):
                buffer.append(chunk)
        except (OSError, ValueError):
            return
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _quiet(
        self, args: list[str], *, timeout: float
    ) -> subprocess.CompletedProcess[str] | None:
        """Run a runtime housekeeping command, tolerating a runtime that is gone."""
        try:
            return subprocess.run(
                args, capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return None
