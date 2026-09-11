"""A Docker API owned by one run, never the host's API (ADR 14)."""

from __future__ import annotations

import re
import subprocess
import tempfile
import time
import uuid

from engineering_team.docker_labels import label_arguments


class RunDaemonStartupError(RuntimeError):
    """The isolated daemon could not be prepared before the run deadline."""


class RunDaemon:
    """Own an internal network and an unprivileged rootless Docker daemon.

    Suite images must already exist in the host cache. Image archives travel
    through a pipe; neither a host socket nor a filesystem mount enters dind.
    ``deadline`` is an absolute ``time.monotonic()`` deadline.
    """

    environment = (
        ("DOCKER_HOST", "tcp://dind:2375"),
        ("TESTCONTAINERS_RYUK_DISABLED", "true"),
        ("TESTCONTAINERS_HOST_OVERRIDE", "dind"),
        ("DOCKER_TLS_CERTDIR", ""),
    )

    def __init__(self, *, image: str, images: tuple[str, ...],
                 runtime: str = "docker", run_id: str | None = None,
                 project: str = "") -> None:
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-fA-F]{64}", image):
            raise ValueError("run daemon image must be pinned by digest")
        if any(not name or name.startswith("-") or any(c.isspace() for c in name)
               for name in images):
            raise ValueError("suite images must be explicit image references")
        self.image = image
        self.images = tuple(dict.fromkeys(images))
        self.runtime = runtime
        # The daemon and its network are resources like any other, and say so
        # (ADR 16): a crashed run leaves both behind, and the sweep removes them
        # only because they carry the run they belonged to.
        self.labels = label_arguments(run_id or "", project)
        label = re.sub(r"[^a-zA-Z0-9_-]", "-", run_id or "run")[:32]
        self.name = f"aset-dind-{label}-{uuid.uuid4().hex[:12]}"
        self.network = self.name + "-net"
        self._network_attempted = False
        self._container_attempted = False
        self._ready = False

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RunDaemonStartupError("run daemon startup deadline exceeded")
        return remaining

    def _run(self, args: list[str], deadline: float, *, check: bool = True):
        result = subprocess.run(
            [self.runtime, *args], capture_output=True,
            timeout=self._remaining(deadline), check=False,
        )
        if check and result.returncode:
            detail = result.stderr.decode(errors="replace")[-2000:]
            raise RunDaemonStartupError(f"run daemon {args[0]} failed: {detail}")
        return result

    def up(self, deadline: float) -> RunDaemon:
        if self._ready:
            return self
        self._remaining(deadline)
        try:
            self._network_attempted = True
            self._run(["network", "create", "--internal", *self.labels,
                       self.network], deadline)
            self._container_attempted = True
            self._run([
                "run", "--detach", "--name", self.name, *self.labels,
                "--network", self.network, "--network-alias", "dind",
                "--security-opt", "seccomp=unconfined",
                "--security-opt", "systempaths=unconfined",
                "--device", "/dev/net/tun", "--memory", "1g",
                "--cpus", "1", "--pids-limit", "512",
                "--env", "DOCKER_TLS_CERTDIR=", self.image,
                "--host=tcp://0.0.0.0:2375", "--tls=false",
            ], deadline)
            while self._run(["exec", self.name, "docker", "--host=tcp://127.0.0.1:2375", "info"],
                            deadline, check=False).returncode:
                time.sleep(min(0.2, self._remaining(deadline)))
            for image in self.images:
                cached = self._run(["image", "inspect", image], deadline, check=False)
                if cached.returncode:
                    raise RunDaemonStartupError(f"suite image missing from host cache: {image}")
                self._seed(image, deadline)
            self._ready = True
            return self
        except Exception as exc:
            self.down()
            if isinstance(exc, RunDaemonStartupError):
                raise
            raise RunDaemonStartupError(f"run daemon startup failed: {exc}") from exc

    def _seed(self, image: str, deadline: float) -> None:
        # Files absorb stderr without an unread pipe deadlocking either process.
        with tempfile.TemporaryFile() as save_errors, tempfile.TemporaryFile() as load_errors:
            processes = []
            try:
                save = subprocess.Popen([self.runtime, "save", image],
                                        stdout=subprocess.PIPE, stderr=save_errors)
                processes.append(save)
                assert save.stdout is not None
                load = subprocess.Popen(
                    [self.runtime, "exec", "-i", self.name, "docker",
                     "--host=tcp://127.0.0.1:2375", "load"],
                    stdin=save.stdout, stdout=subprocess.DEVNULL, stderr=load_errors,
                )
                processes.append(load)
                save.stdout.close()
                load.wait(timeout=self._remaining(deadline))
                save.wait(timeout=self._remaining(deadline))
                if save.returncode or load.returncode:
                    raise RunDaemonStartupError(f"failed to pre-seed suite image: {image}")
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.wait()

    def down(self) -> None:
        """Best-effort bounded cleanup, including partially created resources."""
        self._ready = False
        actions = []
        if self._container_attempted:
            actions.append(["rm", "-f", "-v", self.name])
        if self._network_attempted:
            actions.append(["network", "rm", self.network])
        for args in actions:
            try:
                subprocess.run([self.runtime, *args], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._container_attempted = self._network_attempted = False

    close = down
