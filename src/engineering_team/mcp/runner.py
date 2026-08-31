"""Where a target project's commands execute.

A runner answers one question: given a command, run it under a boundary and
return what it produced. It does not know which commands matter or what their
output means -- that belongs to the quality layer and to each stack profile.

`ProcessRunner` is the boundary this project started with: an OS process sandbox,
`sandbox-exec` on Darwin and Bubblewrap on Linux, refusing to run anywhere else
rather than running unprotected. See `docs/architecture/decisions/0002-container-runner.md`
for why a container backend is intended to replace it, and why this one stays as
the fallback for hosts without a container runtime.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

_VENV_BIN = "Scripts" if os.name == "nt" else "bin"
_OUTPUT_LIMIT = 4096
_SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
_BUBBLEWRAP_CANDIDATES = (Path("/usr/bin/bwrap"), Path("/bin/bwrap"))
_QUALITY_TOOL_PATHS_ENV = "ASET_QUALITY_TOOL_PATHS"
_ENVIRONMENT_MARKER = ".aset-quality-owner"
_ENVIRONMENT_SCHEMA = "aset-quality-v1"
_PASSTHROUGH_ENVIRONMENT = {
    "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "NUMBER_OF_PROCESSORS", "OS",
    "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT", "TERM", "WINDIR",
}


def _remaining(deadline: float) -> float:
    """Seconds left before the deadline, never negative."""
    return max(0.0, deadline - time.monotonic())


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _temporary_path_roots() -> tuple[Path, ...]:
    candidates = (
        Path(tempfile.gettempdir()),
        Path("/tmp"),
        Path("/var/tmp"),
        Path("/private/tmp"),
        Path("/private/var/folders"),
        Path("/run/user"),
        Path("/dev/shm"),
    )
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _sensitive_path_roots(
    workspace: Path | None = None,
    environment: Path | None = None,
) -> tuple[Path, ...]:
    candidates = (
        Path.home(),
        workspace,
        environment,
        Path("/Users"),
        Path("/home"),
        Path("/root"),
        *_temporary_path_roots(),
    )
    resolved: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            value = candidate.resolve()
        except OSError:
            continue
        if value not in resolved:
            resolved.append(value)
    return tuple(resolved)


def _configured_tool_paths(
    workspace: Path | None,
    environment: Path | None,
) -> tuple[Path, ...]:
    configured = os.environ.get(_QUALITY_TOOL_PATHS_ENV, "").strip()
    if not configured:
        return ()
    home = Path.home().resolve()
    forbidden = tuple(
        path.resolve()
        for path in (workspace, environment)
        if path is not None
    )
    temporary = _temporary_path_roots()
    selected: list[Path] = []
    for raw in configured.split(os.pathsep):
        candidate = Path(raw)
        if not raw or not candidate.is_absolute():
            raise RuntimeError(f"{_QUALITY_TOOL_PATHS_ENV} requires absolute paths")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(
                f"{_QUALITY_TOOL_PATHS_ENV} path is unavailable"
            ) from exc
        if (
            not resolved.is_dir()
            or resolved == home
            or home not in resolved.parents
            or _is_within(resolved, forbidden)
            or _is_within(resolved, temporary)
        ):
            raise RuntimeError(f"{_QUALITY_TOOL_PATHS_ENV} path is not permitted")
        if resolved not in selected:
            selected.append(resolved)
    return tuple(selected)


def _system_path_entries(
    workspace: Path | None = None,
    environment: Path | None = None,
) -> list[str]:
    """Return self-contained system tool paths, never private/stateful roots.

    Tools whose installation or state lives below HOME (for example rustup or
    cargo shims) are intentionally unavailable. A run that needs one must
    provision it inside the isolated workspace or quality environment.
    """
    candidates = [*os.environ.get("PATH", os.defpath).split(os.pathsep)]
    candidates.extend(("/usr/bin", "/bin", "/usr/sbin", "/sbin"))
    sensitive = _sensitive_path_roots(workspace, environment)
    entries: list[str] = []
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_absolute():
            continue
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_dir():
            continue
        if resolved == Path("/"):
            continue
        if _is_within(resolved, sensitive):
            continue
        value = str(resolved)
        if value not in entries:
            entries.append(value)
    for configured in _configured_tool_paths(workspace, environment):
        value = str(configured)
        if value not in entries:
            entries.append(value)
    return entries


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


@dataclass

class _ActiveProcess:
    process: subprocess.Popen[bytes]
    process_group: int | None
    descendants: set[int] = field(default_factory=set)
    descendants_lock: threading.Lock = field(default_factory=threading.Lock)
    monitor_stop: threading.Event = field(default_factory=threading.Event)
    monitor_thread: threading.Thread | None = None


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


class ProcessRunner:
    """Runs commands under an OS process sandbox on the host kernel."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.environment: Path | None = None
        self._active_lock = threading.Lock()
        self._active_processes: dict[int, _ActiveProcess] = {}
        self._closing = threading.Event()

    def require_available(self) -> None:
        self._require_sandbox()

    @property
    def closing(self) -> bool:
        return self._closing.is_set()

    def prepare_environment(self, deadline: float) -> str:
        """Build one strict, ephemeral interpreter on the host and return its path.

        The path is a host path because this runner executes on the host. A
        backend whose boundary is elsewhere returns a path in its own namespace;
        the caller only ever passes it back to `execute`.
        """
        self._scavenge_environments()
        base = self._prepare_environment_root()
        directory = Path(tempfile.mkdtemp(prefix="env-", dir=base))
        self.environment = directory
        try:
            base_interpreter = self._base_interpreter()
            uid = os.getuid() if hasattr(os, "getuid") else 0
            (directory / _ENVIRONMENT_MARKER).write_text(
                json.dumps({
                    "schema": _ENVIRONMENT_SCHEMA,
                    "uid": uid,
                    "pid": os.getpid(),
                }, separators=(",", ":")),
                encoding="utf-8",
            )
            created = self._execute_process(
                [
                    base_interpreter, "-I", "-m", "venv", "--without-pip",
                    str(directory),
                ],
                cwd=Path(base_interpreter).parent,
                deadline=deadline,
                allow_network=False,
            )
            if created.returncode != 0:
                raise RuntimeError(f"venv creation failed: {created.stderr[-1000:]}")
            interpreter = str(directory / _VENV_BIN / "python")
            completed = self._execute_process(
                [interpreter, "-I", "-m", "ensurepip", "--upgrade"],
                cwd=directory,
                deadline=deadline,
                allow_network=False,
                allow_subprocesses=True,
            )
            if completed.returncode != 0:
                output = (completed.stdout + completed.stderr)[-1000:]
                raise RuntimeError(f"ensurepip failed: {output}")
        except Exception:
            self.environment = None
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return interpreter

    def execute(self, request: CommandRequest) -> subprocess.CompletedProcess[str]:
        return self._execute_process(
            list(request.args),
            cwd=request.cwd,
            deadline=request.deadline,
            allow_network=request.allow_network,
            allow_subprocesses=request.allow_subprocesses,
            extra_env=request.env,
        )

    def close(self) -> None:
        """Terminate every process this runner started and drop its environment."""
        self._closing.set()
        with self._active_lock:
            active = tuple(self._active_processes.values())
        for item in active:
            self._terminate_process_tree(item)
        directory = self.environment
        self.environment = None
        if directory is not None:
            try:
                shutil.rmtree(directory)
            except FileNotFoundError:
                pass
            try:
                self._environment_root().rmdir()
            except OSError:
                # Another live/crashed environment still owns an entry.
                pass

    @staticmethod
    def _sandbox_backend() -> tuple[str, str]:
        if sys.platform == "darwin":
            try:
                metadata = _SANDBOX_EXECUTABLE.lstat()
            except OSError as exc:
                raise RuntimeError("quality process sandbox is unavailable") from exc
            if not stat.S_ISREG(metadata.st_mode) or not os.access(
                _SANDBOX_EXECUTABLE, os.X_OK
            ):
                raise RuntimeError("quality process sandbox is unavailable")
            return "darwin", str(_SANDBOX_EXECUTABLE)
        if sys.platform.startswith("linux"):
            executable = ProcessRunner._trusted_system_executable(
                _BUBBLEWRAP_CANDIDATES
            )
            return "linux", str(executable)
        raise RuntimeError("quality process sandbox is unavailable on this platform")

    @staticmethod
    def _trusted_system_executable(candidates: tuple[Path, ...]) -> Path:
        """Select a root-owned immutable executable without consulting PATH."""
        for candidate in candidates:
            if not candidate.is_absolute():
                continue
            try:
                candidate_metadata = candidate.lstat()
                resolved = candidate.resolve(strict=True)
                resolved_metadata = resolved.lstat()
            except OSError:
                continue
            if (
                stat.S_ISLNK(candidate_metadata.st_mode)
                or not stat.S_ISREG(candidate_metadata.st_mode)
                or not stat.S_ISREG(resolved_metadata.st_mode)
                or candidate_metadata.st_uid != 0
                or resolved_metadata.st_uid != 0
                or candidate_metadata.st_mode & 0o022
                or resolved_metadata.st_mode & 0o022
                or not os.access(resolved, os.X_OK)
            ):
                continue
            return resolved
        raise RuntimeError("quality process sandbox is unavailable")

    @classmethod
    def _require_sandbox(cls) -> None:
        cls._sandbox_backend()

    def _sandbox_command(
        self,
        args: list[str],
        *,
        allow_network: bool,
        allow_subprocesses: bool = False,
        cwd: Path | None = None,
    ) -> list[str]:
        """Wrap a command in a write-confined sandbox inherited by descendants."""
        backend, executable = self._sandbox_backend()
        environment = self.environment
        if environment is None:
            raise RuntimeError("quality environment has not been created")
        if backend == "linux":
            return self._bubblewrap_command(
                executable,
                args,
                allow_network=allow_network,
                cwd=cwd or self.workspace,
            )
        return self._darwin_sandbox_command(
            executable,
            args,
            allow_network=allow_network,
            allow_subprocesses=allow_subprocesses,
        )

    def _darwin_sandbox_command(
        self,
        executable: str,
        args: list[str],
        *,
        allow_network: bool,
        allow_subprocesses: bool,
    ) -> list[str]:
        environment = self.environment
        if environment is None:
            raise RuntimeError("quality environment has not been created")
        workspace_literal = json.dumps(str(self.workspace), ensure_ascii=False)
        environment_literal = json.dumps(str(environment), ensure_ascii=False)
        path_literals = [
            json.dumps(entry, ensure_ascii=False)
            for entry in _system_path_entries(self.workspace, environment)
        ]
        sensitive = _sensitive_path_roots(self.workspace, environment)
        runtime_literals: list[str] = []
        for candidate in (Path(sys.prefix), Path(sys.base_prefix)):
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if not _is_within(resolved, sensitive):
                runtime_literals.append(json.dumps(str(resolved), ensure_ascii=False))
        profile = "\n".join([
            "(version 1)",
            "(deny default)",
            *(
                ["(allow process*)"]
                if allow_subprocesses
                else ["(allow process-exec)", "(deny process-fork)"]
            ),
            "(allow sysctl-read)",
            "(allow file-read-metadata)",
            "(allow file-read*",
            "  (require-all",
            '    (require-not (subpath "/Users"))',
            '    (require-not (subpath "/home"))',
            '    (require-not (subpath "/root"))',
            '    (require-not (subpath "/Volumes"))',
            '    (require-not (subpath "/tmp"))',
            '    (require-not (subpath "/var/tmp"))',
            '    (require-not (subpath "/private/tmp"))',
            '    (require-not (subpath "/private/var/tmp"))',
            '    (require-not (subpath "/private/var/folders"))',
            '    (require-not (subpath "/dev/shm"))',
            '    (require-not (subpath "/run/user"))))',
            "(allow file-read*",
            f"  (subpath {workspace_literal})",
            f"  (subpath {environment_literal})",
            *(f"  (subpath {literal})" for literal in runtime_literals),
            *(f"  (subpath {literal})" for literal in path_literals),
            '  (literal "/dev/null"))',
            "(allow file-write*",
            f"  (subpath {workspace_literal})",
            f"  (subpath {environment_literal})",
            '  (literal "/dev/null"))',
            *(
                [
                    "(allow network*)",
                    "(allow mach-lookup",
                    '  (global-name "com.apple.SecurityServer")',
                    '  (global-name "com.apple.trustd")',
                    '  (global-name "com.apple.trustd.agent"))',
                ]
                if allow_network
                else []
            ),
        ])
        return [
            executable,
            "-p", profile,
            *args,
        ]

    def _bubblewrap_command(
        self,
        executable: str,
        args: list[str],
        *,
        allow_network: bool,
        cwd: Path,
    ) -> list[str]:
        """Build a minimal Linux mount namespace without exposing host root/home."""
        environment = self.environment
        if environment is None:
            raise RuntimeError("quality environment has not been created")

        writable = (self.workspace, environment)
        readonly_candidates = [
            Path("/usr"),
            Path("/bin"),
            Path("/lib"),
            Path("/lib64"),
            Path("/sbin"),
            Path("/etc/ssl"),
            Path("/etc/pki"),
            Path("/etc/ca-certificates"),
            Path("/etc/ld.so.cache"),
            Path("/etc/ld.so.conf"),
            Path("/etc/ld.so.conf.d"),
            Path("/etc/resolv.conf"),
            Path("/etc/hosts"),
            Path("/etc/nsswitch.conf"),
            Path("/etc/passwd"),
            Path("/etc/group"),
            Path("/etc/localtime"),
            Path(sys.prefix),
            Path(sys.base_prefix),
            *map(Path, _system_path_entries(self.workspace, environment)),
        ]
        sensitive = _sensitive_path_roots(self.workspace, environment)
        configured_tools = set(_configured_tool_paths(self.workspace, environment))
        readonly: list[tuple[Path, Path]] = []
        seen_destinations: set[Path] = set()
        for candidate in readonly_candidates:
            if not candidate.is_absolute() or not candidate.exists():
                continue
            destination = candidate
            try:
                source = candidate.resolve(strict=True)
            except OSError:
                continue
            if source == Path("/") or destination == Path("/"):
                continue
            if any(
                source == allowed or allowed in source.parents
                for allowed in writable
            ):
                continue
            if (
                source not in configured_tools
                and (
                    _is_within(source, sensitive)
                    or _is_within(destination, sensitive)
                )
            ):
                continue
            if any(
                mounted_destination == destination
                or mounted_destination in destination.parents
                for _, mounted_destination in readonly
                if mounted_destination.is_dir()
            ):
                continue
            if destination in seen_destinations:
                continue
            readonly.append((source, destination))
            seen_destinations.add(destination)

        destinations = [
            (destination, source.is_dir()) for source, destination in readonly
        ]
        destinations.extend((path, True) for path in writable)
        destinations.extend(((cwd, True), (Path("/home/aset"), True)))
        directories: set[Path] = set()
        for destination, is_directory in destinations:
            parent = destination if is_directory else destination.parent
            while parent != Path("/"):
                if parent not in {Path("/home"), Path("/tmp")}:
                    directories.add(parent)
                parent = parent.parent

        command = [
            executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            *( ["--share-net"] if allow_network else [] ),
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/home",
        ]
        for directory in sorted(directories, key=lambda path: (len(path.parts), str(path))):
            command.extend(("--dir", str(directory)))
        for source, destination in readonly:
            command.extend(("--ro-bind", str(source), str(destination)))
        # Keep the workspace first: callers and tests can audit the writable
        # surface from the first bind without inferring mount ordering.
        for source in writable:
            command.extend(("--bind", str(source), str(source)))
        command.extend((
            "--setenv", "HOME", "/home/aset",
            "--setenv", "USERPROFILE", "/home/aset",
            "--setenv", "TMPDIR", "/tmp",
            "--setenv", "TMP", "/tmp",
            "--setenv", "TEMP", "/tmp",
            "--chdir", str(cwd),
            "--",
            *args,
        ))
        return command

    def _subprocess_environment(self) -> dict[str, str]:
        directory = self.environment
        if directory is None:
            raise RuntimeError("quality environment has not been created")
        home = directory / "home"
        temporary = directory / "tmp"
        home.mkdir(exist_ok=True)
        temporary.mkdir(exist_ok=True)
        environment = {
            name: value for name, value in os.environ.items()
            if name.upper() in _PASSTHROUGH_ENVIRONMENT
        }
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home),
            "PATH": os.pathsep.join(
                [
                    str(directory / _VENV_BIN),
                    *_system_path_entries(self.workspace, directory),
                ]
            ),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONNOUSERSITE": "1",
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "TMPDIR": str(temporary),
            "USERPROFILE": str(home),
            "VIRTUAL_ENV": str(directory),
        })
        return environment

    @staticmethod
    def _process_group_options() -> dict[str, object]:
        if os.name == "nt":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    def _execute_process(
        self,
        args: list[str],
        *,
        cwd: Path,
        deadline: float,
        allow_network: bool = False,
        allow_subprocesses: bool = False,
        extra_env: tuple[tuple[str, str], ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        timeout = _remaining(deadline)
        stdout_buffer = _BoundedOutput()
        stderr_buffer = _BoundedOutput()
        sandboxed_args = self._sandbox_command(
            args,
            allow_network=allow_network,
            allow_subprocesses=allow_subprocesses,
            cwd=cwd,
        )
        with self._active_lock:
            if self._closing.is_set():
                raise RuntimeError("quality environment is closing")
            process = subprocess.Popen(
                sandboxed_args,
                cwd=cwd,
                env={**self._subprocess_environment(), **dict(extra_env or ())},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **self._process_group_options(),
            )
            process_group = os.getpgid(process.pid) if os.name != "nt" else None
            active = _ActiveProcess(process, process_group)
            self._active_processes[process.pid] = active
            if allow_subprocesses and os.name != "nt":
                active.monitor_thread = threading.Thread(
                    target=self._monitor_process_descendants,
                    args=(active,),
                    name=f"quality-descendants-{process.pid}",
                    daemon=True,
                )
                active.monitor_thread.start()
        assert process.stdout is not None
        assert process.stderr is not None
        stop_readers = threading.Event()
        readers = (
            threading.Thread(
                target=self._drain_stream,
                args=(process.stdout, stdout_buffer, stop_readers),
                name=f"quality-output-{process.pid}-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=self._drain_stream,
                args=(process.stderr, stderr_buffer, stop_readers),
                name=f"quality-output-{process.pid}-stderr",
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        timed_out: subprocess.TimeoutExpired | None = None
        try:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                timed_out = exc
                self._terminate_process_tree(active)
        finally:
            # A setsid descendant can retain a pipe after the parent exits. The
            # readers use nonblocking descriptors and explicit cancellation, so
            # neither a daemon thread nor a file descriptor survives this call.
            for reader in readers:
                reader.join(timeout=0.05)
            stop_readers.set()
            for reader in readers:
                reader.join(timeout=0.25)
            self._stop_descendant_monitor(active)
            with self._active_lock:
                self._active_processes.pop(process.pid, None)
        if timed_out is not None:
            raise subprocess.TimeoutExpired(
                args,
                timeout,
                output=stdout_buffer.text(),
                stderr=stderr_buffer.text(),
            ) from timed_out
        return subprocess.CompletedProcess(
            args, process.returncode, stdout_buffer.text(), stderr_buffer.text()
        )

    @staticmethod
    def _drain_stream(
        stream, output: _BoundedOutput, stop: threading.Event | None = None
    ) -> None:
        stop = stop or threading.Event()
        try:
            descriptor = stream.fileno()
            if os.name != "nt":
                os.set_blocking(descriptor, False)
                while not stop.is_set():
                    try:
                        chunk = os.read(descriptor, 64 * 1024)
                    except BlockingIOError:
                        stop.wait(0.01)
                        continue
                    if not chunk:
                        break
                    output.append(chunk)
            else:
                while not stop.is_set() and (chunk := stream.read(64 * 1024)):
                    output.append(chunk)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    @classmethod
    def _terminate_process_tree(cls, active: _ActiveProcess) -> None:
        process = active.process
        if os.name == "nt":
            cls._terminate_windows_tree(process)
            return
        with active.descendants_lock:
            descendants = set(active.descendants)
        descendants.update(cls._descendant_pids(process.pid))
        process_group = active.process_group
        if process_group is None:
            return
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        descendants.update(cls._descendant_pids(process.pid))
        cls._signal_pids(descendants, signal.SIGTERM)
        end = time.monotonic() + 0.1
        while time.monotonic() < end:
            cls._signal_pids(descendants, signal.SIGTERM)
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                break
            time.sleep(0.01)
        try:
            os.killpg(process_group, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass
        cls._signal_pids(descendants, signal.SIGKILL)
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()

    @staticmethod
    def _descendant_pids(root_pid: int) -> set[int]:
        """Snapshot descendants before a child can escape its process group."""
        try:
            completed = subprocess.run(
                ["/bin/ps", "-axo", "pid=,ppid="],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return set()
        children: dict[int, set[int]] = {}
        for line in completed.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            try:
                pid, parent = map(int, fields)
            except ValueError:
                continue
            children.setdefault(parent, set()).add(pid)
        descendants: set[int] = set()
        pending = list(children.get(root_pid, ()))
        while pending:
            pid = pending.pop()
            if pid in descendants or pid in {os.getpid(), root_pid}:
                continue
            descendants.add(pid)
            pending.extend(children.get(pid, ()))
        return descendants

    @classmethod
    def _monitor_process_descendants(cls, active: _ActiveProcess) -> None:
        while not active.monitor_stop.is_set():
            discovered = cls._descendant_pids(active.process.pid)
            if discovered:
                with active.descendants_lock:
                    active.descendants.update(discovered)
            active.monitor_stop.wait(0.05)

    @classmethod
    def _stop_descendant_monitor(cls, active: _ActiveProcess) -> None:
        active.monitor_stop.set()
        monitor = active.monitor_thread
        if monitor is not None:
            monitor.join(timeout=0.3)
        with active.descendants_lock:
            descendants = set(active.descendants)
        if not descendants:
            return
        cls._signal_pids(descendants, signal.SIGTERM)
        time.sleep(0.02)
        cls._signal_pids(descendants, signal.SIGKILL)

    @staticmethod
    def _signal_pids(pids: set[int], requested_signal: signal.Signals) -> None:
        for pid in pids:
            try:
                os.kill(pid, requested_signal)
            except (PermissionError, ProcessLookupError):
                continue

    @staticmethod
    def _terminate_windows_tree(process: subprocess.Popen[bytes]) -> None:
        system_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        taskkill = system_root / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    @staticmethod
    def _environment_root() -> Path:
        uid = os.getuid() if hasattr(os, "getuid") else 0
        return Path(tempfile.gettempdir()).resolve() / f"aset-quality-{uid}"

    @classmethod
    def _prepare_environment_root(cls) -> Path:
        root = cls._environment_root()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("quality environment root is not a real directory")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise RuntimeError("quality environment root has a foreign owner")
        if metadata.st_mode & 0o077:
            root.chmod(0o700)
        return root

    @classmethod
    def _scavenge_environments(cls) -> None:
        """Remove crashed environments, but only below our private owned root.

        A valid marker and a dead producer PID are both required. Unknown,
        symlinked, or currently-live entries are deliberately left alone.
        """
        root = cls._prepare_environment_root()
        uid = os.getuid() if hasattr(os, "getuid") else 0
        for directory in root.glob("env-*"):
            try:
                metadata = directory.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISDIR(metadata.st_mode)
                    or (hasattr(os, "getuid") and metadata.st_uid != uid)
                ):
                    continue
                marker = directory / _ENVIRONMENT_MARKER
                marker_metadata = marker.lstat()
                if stat.S_ISLNK(marker_metadata.st_mode) or not stat.S_ISREG(
                    marker_metadata.st_mode
                ):
                    continue
                owner = json.loads(marker.read_text(encoding="utf-8"))
                if not isinstance(owner, dict):
                    continue
                if owner != {
                    "schema": _ENVIRONMENT_SCHEMA,
                    "uid": uid,
                    "pid": int(owner.get("pid", -1)),
                }:
                    continue
                if cls._process_is_alive(int(owner["pid"])):
                    continue
                shutil.rmtree(directory)
            except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
                continue

    @staticmethod
    def _process_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _base_interpreter(self) -> str:
        """Use the system/base runtime, never an operator-home virtualenv."""
        raw = getattr(sys, "_base_executable", None) or sys.executable
        try:
            executable = Path(raw).resolve(strict=True)
            metadata = executable.lstat()
        except OSError as exc:
            raise RuntimeError("trusted base interpreter is unavailable") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not os.access(executable, os.X_OK)
            or _is_within(
                executable,
                _sensitive_path_roots(self.workspace, self.environment),
            )
        ):
            raise RuntimeError("trusted base interpreter is unavailable")
        return str(executable)
