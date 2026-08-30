from __future__ import annotations

import ast
import atexit
import importlib.metadata
import json
import os
import re
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

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult

_VENV_BIN = "Scripts" if os.name == "nt" else "bin"
_DISTRIBUTION_NAME = "autonomous-engineering-team"
_OUTPUT_LIMIT = 4096
_ENVIRONMENT_MARKER = ".aset-quality-owner"
_ENVIRONMENT_SCHEMA = "aset-quality-v1"
_SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
_BUBBLEWRAP_CANDIDATES = (Path("/usr/bin/bwrap"), Path("/bin/bwrap"))
_QUALITY_TOOL_PATHS_ENV = "ASET_QUALITY_TOOL_PATHS"
_PASSTHROUGH_ENVIRONMENT = {
    "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "NUMBER_OF_PROCESSORS", "OS",
    "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT", "TERM", "WINDIR",
}


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


class QualityMCP:
    def __init__(self, root: str | Path, *, timeout_seconds: float = 60) -> None:
        self.root = Path(root).resolve()
        self.timeout_seconds = float(timeout_seconds)
        self._last: dict[str, ToolResult] = {}
        self._project_prepared = False
        self._project_result: ToolResult | None = None
        self._prepared_tools: set[str] = set()
        self._python: str | None = None
        self._environment: Path | None = None
        self._environment_lock = threading.RLock()
        self._mutation_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_processes: dict[int, _ActiveProcess] = {}
        self._closing = threading.Event()
        self._closed = False

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
            executable = QualityMCP._trusted_system_executable(
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
        environment = self._environment
        if environment is None:
            raise RuntimeError("quality environment has not been created")
        if backend == "linux":
            return self._bubblewrap_command(
                executable,
                args,
                allow_network=allow_network,
                cwd=cwd or self.root,
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
        environment = self._environment
        if environment is None:
            raise RuntimeError("quality environment has not been created")
        workspace_literal = json.dumps(str(self.root), ensure_ascii=False)
        environment_literal = json.dumps(str(environment), ensure_ascii=False)
        path_literals = [
            json.dumps(entry, ensure_ascii=False)
            for entry in _system_path_entries(self.root, environment)
        ]
        sensitive = _sensitive_path_roots(self.root, environment)
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
        environment = self._environment
        if environment is None:
            raise RuntimeError("quality environment has not been created")

        writable = (self.root, environment)
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
            *map(Path, _system_path_entries(self.root, environment)),
        ]
        sensitive = _sensitive_path_roots(self.root, environment)
        configured_tools = set(_configured_tool_paths(self.root, environment))
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

    def _deadline(self) -> float:
        return time.monotonic() + self.timeout_seconds

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("quality operation deadline exceeded")
        return remaining

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
                _sensitive_path_roots(self.root, self._environment),
            )
        ):
            raise RuntimeError("trusted base interpreter is unavailable")
        return str(executable)

    def _interpreter(self, deadline: float | None = None) -> str:
        """Create one strict, ephemeral interpreter for this QualityMCP instance."""
        deadline = self._deadline() if deadline is None else deadline
        self._require_sandbox()
        if not self._environment_lock.acquire(timeout=self._remaining(deadline)):
            raise TimeoutError("quality environment lock deadline exceeded")
        try:
            if self._closed or self._closing.is_set():
                raise RuntimeError("quality environment is closed")
            if self._python is not None:
                return self._python
            self._scavenge_environments()
            base = self._prepare_environment_root()
            directory = Path(tempfile.mkdtemp(prefix="env-", dir=base))
            self._environment = directory
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
                self._python = str(directory / _VENV_BIN / "python")
                completed = self._execute_process(
                    [self._python, "-I", "-m", "ensurepip", "--upgrade"],
                    cwd=directory,
                    deadline=deadline,
                    allow_network=False,
                    allow_subprocesses=True,
                )
                if completed.returncode != 0:
                    output = (completed.stdout + completed.stderr)[-1000:]
                    raise RuntimeError(f"ensurepip failed: {output}")
            except Exception:
                self._python = None
                self._environment = None
                shutil.rmtree(directory, ignore_errors=True)
                raise
            atexit.register(self.close)
            return self._python
        finally:
            self._environment_lock.release()

    def _subprocess_environment(self) -> dict[str, str]:
        directory = self._environment
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
                    *_system_path_entries(self.root, directory),
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
    ) -> subprocess.CompletedProcess[str]:
        timeout = self._remaining(deadline)
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
                env=self._subprocess_environment(),
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

    def close(self) -> None:
        """Terminate active process groups and remove the ephemeral environment."""
        self._closing.set()
        with self._active_lock:
            active = tuple(self._active_processes.values())
        for item in active:
            self._terminate_process_tree(item)
        with self._environment_lock:
            if self._closed:
                return
            self._closed = True
            with self._active_lock:
                active = tuple(self._active_processes.values())
            for item in active:
                self._terminate_process_tree(item)
            directory = self._environment
            self._environment = None
            self._python = None
            atexit.unregister(self.close)
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

    def _denied(self, role: AgentRole, tool: str) -> ToolResult:
        return ToolResult(
            tool_name=tool, allowed_role=role, status=ToolStatus.DENIED,
            input_summary="denied", output_summary="", duration_ms=0, error="role denied",
        )

    def _unavailable(
        self, role: AgentRole, tool: str, exc: BaseException, started: float
    ) -> ToolResult:
        result = ToolResult(
            tool_name=tool,
            allowed_role=role,
            status=ToolStatus.UNAVAILABLE,
            input_summary="safe",
            output_summary="",
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"isolated environment unavailable: {type(exc).__name__}: {exc}",
        )
        self._last[tool] = result
        return result

    def _operation_failure(
        self, result: ToolResult, role: AgentRole, tool: str
    ) -> ToolResult:
        failure = result.model_copy(update={"tool_name": tool, "allowed_role": role})
        self._last[tool] = failure
        return failure

    def _run_python(
        self,
        role: AgentRole,
        tool: str,
        module: str,
        arguments: list[str],
        allowed: set[AgentRole],
        deadline: float,
        *,
        cwd: Path | None = None,
        allow_network: bool = False,
    ) -> ToolResult:
        if role not in allowed:
            return self._denied(role, tool)
        started = time.perf_counter()
        try:
            interpreter = self._interpreter(deadline)
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return self._unavailable(role, tool, exc, started)
        return self._run(
            role,
            tool,
            [interpreter, "-I", "-m", module, *arguments],
            allowed,
            deadline,
            cwd=cwd or self.root,
            started=started,
            allow_network=allow_network,
        )

    def _run(
        self,
        role: AgentRole,
        tool: str,
        args: list[str],
        allowed: set[AgentRole],
        deadline: float,
        *,
        cwd: Path,
        started: float | None = None,
        allow_network: bool = False,
    ) -> ToolResult:
        if role not in allowed:
            return self._denied(role, tool)
        started = time.perf_counter() if started is None else started
        try:
            completed = self._execute_process(
                args,
                cwd=cwd,
                deadline=deadline,
                allow_network=allow_network,
                allow_subprocesses=allow_network,
            )
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return self._unavailable(role, tool, exc, started)
        output = (completed.stdout + completed.stderr)[-4000:]
        if completed.returncode < 0:
            return self._unavailable(
                role, tool, RuntimeError("quality subprocess was terminated"), started
            )
        status = ToolStatus.SUCCESS if completed.returncode == 0 else ToolStatus.FAIL
        result = ToolResult(
            tool_name=tool,
            allowed_role=role,
            status=status,
            input_summary="safe",
            output_summary=output,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self._last[tool] = result
        return result

    def _prepare_quality_tools(
        self,
        role: AgentRole,
        tool: str,
        modules: tuple[str, ...],
        allowed: set[AgentRole],
        deadline: float,
    ) -> ToolResult | None:
        started = time.perf_counter()
        try:
            acquired = self._mutation_lock.acquire(timeout=self._remaining(deadline))
        except TimeoutError as exc:
            return self._unavailable(role, tool, exc, started)
        if not acquired:
            return self._unavailable(
                role,
                tool,
                TimeoutError("quality mutation lock deadline exceeded"),
                started,
            )
        try:
            missing = [module for module in modules if module not in self._prepared_tools]
            if not missing:
                return None
            try:
                environment = Path(self._interpreter(deadline)).parent.parent
            except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
                return self._unavailable(role, tool, exc, time.perf_counter())
            try:
                requirements = list(self._quality_toolchain_requirements())
            except RuntimeError as exc:
                return self._unavailable(role, tool, exc, started)
            # The declared list is the complete exact closure. --no-deps prevents
            # pip from adding a floating transitive resolution beside that lock.
            result = self._run_python(
                role,
                "install_quality_tools",
                "pip",
                ["install", "--no-input", "--no-deps", *requirements],
                allowed,
                deadline,
                cwd=environment,
                allow_network=True,
            )
            if result.status is not ToolStatus.SUCCESS:
                return self._operation_failure(result, role, tool)
            self._prepared_tools.update(
                requirement.partition("==")[0] for requirement in requirements
            )
            return None
        finally:
            self._mutation_lock.release()

    @staticmethod
    def _quality_requirement(module: str) -> str:
        for declared in QualityMCP._resolved_quality_toolchain(
            sys.version_info[:2], sys.platform
        ):
            if declared.partition("==")[0].lower() == module.lower():
                return declared
        raise RuntimeError(f"quality tool is not locked in pyproject.toml: {module}")

    @staticmethod
    def _parse_quality_requirement(declared: str) -> tuple[str, str | None]:
        match = re.fullmatch(
            r"\s*([A-Za-z0-9_.-]+==[^*\s;]+)\s*(?:;\s*(.+))?",
            declared,
        )
        if match is None:
            raise RuntimeError("quality toolchain must be a complete set of exact pins")
        return match.group(1), match.group(2)

    @staticmethod
    def _quality_marker_applies(
        marker: str | None,
        python_version: tuple[int, int],
        platform: str,
    ) -> bool:
        if marker is None:
            return True
        terms = re.split(r"\s+and\s+", marker)
        if len(terms) > 1:
            return all(
                QualityMCP._quality_marker_applies(
                    term.strip(), python_version, platform
                )
                for term in terms
            )
        match = re.fullmatch(
            r"\s*(python_version|sys_platform)\s*(==|!=|<=|>=|<|>)\s*"
            r"(['\"])([^'\"]+)\3\s*",
            marker,
        )
        if match is None:
            raise RuntimeError(f"unsupported quality toolchain marker: {marker}")
        variable, operator, _, expected = match.groups()
        actual: tuple[int, int] | str
        wanted: tuple[int, int] | str
        if variable == "python_version":
            version_match = re.fullmatch(r"(\d+)\.(\d+)", expected)
            if version_match is None:
                raise RuntimeError(f"invalid python_version marker: {marker}")
            actual = python_version
            wanted = tuple(map(int, version_match.groups()))
        else:
            actual = platform
            wanted = expected
        comparisons = {
            "==": actual == wanted,
            "!=": actual != wanted,
            "<": actual < wanted,
            "<=": actual <= wanted,
            ">": actual > wanted,
            ">=": actual >= wanted,
        }
        return comparisons[operator]

    @classmethod
    def _resolved_quality_toolchain(
        cls,
        python_version: tuple[int, int],
        platform: str,
    ) -> tuple[str, ...]:
        resolved: list[str] = []
        for declared in cls._quality_toolchain_requirements():
            requirement, marker = cls._parse_quality_requirement(declared)
            if cls._quality_marker_applies(marker, python_version, platform):
                resolved.append(requirement)
        return tuple(resolved)

    @staticmethod
    def _source_quality_toolchain() -> tuple[str, ...]:
        source_pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        if not source_pyproject.is_file():
            return ()
        content = source_pyproject.read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^quality-toolchain\s*=\s*(\[.*?^\])",
            content,
        )
        if match is None:
            return ()
        try:
            parsed = ast.literal_eval(match.group(1))
        except (SyntaxError, ValueError):
            return ()
        if not isinstance(parsed, list) or not all(
            isinstance(item, str) for item in parsed
        ):
            return ()
        return tuple(parsed)

    @staticmethod
    def _metadata_quality_toolchain() -> tuple[str, ...]:
        declared: list[str] = []
        for entry in importlib.metadata.requires(_DISTRIBUTION_NAME) or []:
            requirement, separator, marker = entry.partition(";")
            if not separator:
                continue
            terms = [term.strip().strip("()").strip() for term in re.split(
                r"\s+and\s+", marker
            )]
            extra_terms = [
                term
                for term in terms
                if re.fullmatch(
                    r"extra\s*==\s*(['\"])quality-toolchain\1",
                    term,
                )
            ]
            if not extra_terms:
                continue
            remaining = [term for term in terms if term not in extra_terms]
            declaration = requirement.strip()
            if remaining:
                declaration = f"{declaration}; {' and '.join(remaining)}"
            declared.append(declaration)
        return tuple(declared)

    @classmethod
    def _quality_toolchain_requirements(cls) -> tuple[str, ...]:
        """Load the complete exact toolchain closure from source or wheel metadata."""
        declared = cls._source_quality_toolchain() or cls._metadata_quality_toolchain()
        if not declared:
            raise RuntimeError("quality toolchain must be a complete set of exact pins")
        for item in declared:
            cls._parse_quality_requirement(item)
        return tuple(declared)

    def _prepare_project(
        self, role: AgentRole, tool: str, allowed: set[AgentRole], deadline: float
    ) -> ToolResult | None:
        """Install the project, preferring a local hashed lock or constraints file.

        Every command remains inside the process sandbox. Network is enabled for
        installation only; later build, test, lint, and scan phases are offline.
        """
        started = time.perf_counter()
        try:
            acquired = self._mutation_lock.acquire(timeout=self._remaining(deadline))
        except TimeoutError as exc:
            return self._unavailable(role, tool, exc, started)
        if not acquired:
            return self._unavailable(
                role,
                tool,
                TimeoutError("quality mutation lock deadline exceeded"),
                started,
            )
        try:
            if self._project_prepared:
                if self._project_result is None:
                    return None
                return self._operation_failure(self._project_result, role, tool)
            if not (self.root / "pyproject.toml").is_file():
                self._project_prepared = True
                return None
            lock = self.root / "requirements.lock"
            constraints = self.root / "constraints.txt"
            if lock.is_file():
                commands = [
                    [
                        "install", "--no-input", "--require-hashes",
                        "--no-build-isolation", "-r", str(lock),
                    ],
                    [
                        "install", "--no-input", "--no-deps",
                        "--no-build-isolation", ".",
                    ],
                ]
            elif constraints.is_file():
                commands = [
                    [
                        "install", "--no-input", "--no-build-isolation",
                        "--constraint", str(constraints), ".",
                    ]
                ]
            else:
                commands = [["install", "--no-input", "."]]
            result: ToolResult | None = None
            for arguments in commands:
                result = self._run_python(
                    role,
                    "install_dependencies",
                    "pip",
                    arguments,
                    allowed,
                    deadline,
                    allow_network=True,
                )
                if result.status is not ToolStatus.SUCCESS:
                    break
            self._project_prepared = True
            self._project_result = (
                None if result is not None and result.status is ToolStatus.SUCCESS else result
            )
            if self._project_result is None:
                return None
            return self._operation_failure(self._project_result, role, tool)
        finally:
            self._mutation_lock.release()

    def _static(
        self, role: AgentRole, tool: str, allowed: set[AgentRole], output: str
    ) -> ToolResult:
        if role not in allowed:
            return self._denied(role, tool)
        return ToolResult(
            tool_name=tool, allowed_role=role, status=ToolStatus.SUCCESS,
            input_summary="safe", output_summary=output, duration_ms=0,
        )

    def _get_last(
        self, role: AgentRole, getter: str, source: str, allowed: set[AgentRole]
    ) -> ToolResult:
        if role not in allowed:
            return self._static(role, getter, allowed, "")
        previous = self._last.get(source)
        return ToolResult(
            tool_name=getter,
            allowed_role=role,
            status=previous.status if previous else ToolStatus.UNAVAILABLE,
            input_summary="safe",
            output_summary=previous.output_summary if previous else f"no {source} result",
            duration_ms=0,
            error=previous.error if previous else f"{source} has not executed",
        )

    def run_tests(self, role: AgentRole, paths: list[str] | None = None) -> ToolResult:
        allowed = {AgentRole.TESTING}
        if role not in allowed:
            return self._denied(role, "run_tests")
        deadline = self._deadline()
        prepared = self._prepare_project(role, "run_tests", allowed, deadline)
        if prepared is not None:
            return prepared
        prepared = self._prepare_quality_tools(
            role, "run_tests", ("pytest",), allowed, deadline
        )
        if prepared is not None:
            return prepared
        return self._run_python(
            role, "run_tests", "pytest", paths or [], allowed, deadline
        )

    def get_test_results(self, role: AgentRole) -> ToolResult:
        return self._get_last(
            role, "get_test_results", "run_tests", {AgentRole.TESTING}
        )

    def run_build(self, role: AgentRole) -> ToolResult:
        return self._run_python(
            role, "run_build", "compileall", ["."],
            {AgentRole.DEVELOPER, AgentRole.TESTING}, self._deadline(),
        )

    def get_build_status(self, role: AgentRole) -> ToolResult:
        return self._get_last(
            role, "get_build_status", "run_build", {AgentRole.DEVELOPER, AgentRole.TESTING}
        )

    def run_linter(self, role: AgentRole) -> ToolResult:
        allowed = {AgentRole.DEVELOPER, AgentRole.TESTING}
        if role not in allowed:
            return self._denied(role, "run_linter")
        deadline = self._deadline()
        prepared = self._prepare_quality_tools(
            role, "run_linter", ("ruff",), allowed, deadline
        )
        if prepared is not None:
            return prepared
        return self._run_python(
            role, "run_linter", "ruff",
            ["check", ".", *self._ruff_configuration()],
            allowed, deadline,
        )

    def scan_dependencies(self, role: AgentRole) -> ToolResult:
        allowed = {AgentRole.SECURITY}
        if role not in allowed:
            return self._denied(role, "scan_dependencies")
        deadline = self._deadline()
        prepared = self._prepare_project(role, "scan_dependencies", allowed, deadline)
        if prepared is not None:
            return prepared
        try:
            environment = Path(self._interpreter(deadline)).parent.parent
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return self._unavailable(role, "scan_dependencies", exc, time.perf_counter())
        return self._run_python(
            role, "scan_dependencies", "pip", ["check"], allowed, deadline, cwd=environment
        )

    def _ruff_configuration(self) -> list[str]:
        """Acotar la configuracion de ruff al proyecto, no al arbol de arriba.

        Ruff resuelve su configuracion subiendo por los directorios padre. Un
        proyecto anidado dentro de otro repositorio -el caso de los demos- lo
        lleva a leer el pyproject del padre, que queda fuera del sandbox: falla
        con "Failed to read ... Operation not permitted", Security lo reporta
        como herramienta caida y el Reviewer rechaza por un problema que el
        proyecto no tiene.
        """
        for name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
            candidate = self.root / name
            if candidate.is_file():
                return ["--config", str(candidate)]
        return ["--isolated"]

    def run_security_scan(self, role: AgentRole) -> ToolResult:
        allowed = {AgentRole.SECURITY}
        if role not in allowed:
            return self._denied(role, "run_security_scan")
        deadline = self._deadline()
        prepared = self._prepare_quality_tools(
            role, "run_security_scan", ("ruff",), allowed, deadline
        )
        if prepared is not None:
            return prepared
        target = (
            "app" if (self.root / "app").is_dir()
            else "sample_app/app" if (self.root / "sample_app" / "app").is_dir()
            else "."
        )
        return self._run_python(
            role,
            "run_security_scan",
            "ruff",
            [
                "check", target, "--select", "S", "--extend-exclude",
                "tests,test,test_*.py,*_test.py", *self._ruff_configuration(),
            ],
            allowed,
            deadline,
        )

    def get_security_report(self, role: AgentRole) -> ToolResult:
        return self._get_last(
            role, "get_security_report", "run_security_scan", {AgentRole.SECURITY}
        )
