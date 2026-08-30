from __future__ import annotations

import atexit
import importlib.metadata
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult

_VENV_BIN = "Scripts" if os.name == "nt" else "bin"
_DISTRIBUTION_NAME = "autonomous-engineering-team"
_OUTPUT_LIMIT = 4096
_PASSTHROUGH_ENVIRONMENT = {
    "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "NUMBER_OF_PROCESSORS", "OS", "PATH",
    "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT", "TERM", "WINDIR",
}


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
class _ActiveProcess:
    process: subprocess.Popen[bytes]
    process_group: int | None


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

    def _deadline(self) -> float:
        return time.monotonic() + self.timeout_seconds

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("quality operation deadline exceeded")
        return remaining

    def _interpreter(self, deadline: float | None = None) -> str:
        """Create one strict, ephemeral interpreter for this QualityMCP instance."""
        deadline = self._deadline() if deadline is None else deadline
        if not self._environment_lock.acquire(timeout=self._remaining(deadline)):
            raise TimeoutError("quality environment lock deadline exceeded")
        try:
            if self._closed or self._closing.is_set():
                raise RuntimeError("quality environment is closed")
            if self._python is not None:
                return self._python
            directory = Path(tempfile.mkdtemp(prefix="aset-quality-"))
            self._environment = directory
            try:
                created = self._execute_process(
                    [
                        sys.executable, "-I", "-m", "venv", "--without-pip",
                        str(directory),
                    ],
                    cwd=Path(sys.executable).resolve().parent,
                    deadline=deadline,
                )
                if created.returncode != 0:
                    raise RuntimeError(f"venv creation failed: {created.stderr[-1000:]}")
                self._python = str(directory / _VENV_BIN / "python")
                completed = self._execute_process(
                    [self._python, "-I", "-m", "ensurepip", "--upgrade"],
                    cwd=directory,
                    deadline=deadline,
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
        current_path = environment.get("PATH", os.defpath)
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home),
            "PATH": os.pathsep.join((str(directory / _VENV_BIN), current_path)),
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
        self, args: list[str], *, cwd: Path, deadline: float
    ) -> subprocess.CompletedProcess[str]:
        timeout = self._remaining(deadline)
        stdout_buffer = _BoundedOutput()
        stderr_buffer = _BoundedOutput()
        with self._active_lock:
            if self._closing.is_set():
                raise RuntimeError("quality environment is closing")
            process = subprocess.Popen(
                args,
                cwd=cwd,
                env=self._subprocess_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **self._process_group_options(),
            )
            process_group = os.getpgid(process.pid) if os.name != "nt" else None
            active = _ActiveProcess(process, process_group)
            self._active_processes[process.pid] = active
        assert process.stdout is not None
        assert process.stderr is not None
        readers = (
            threading.Thread(
                target=self._drain_stream, args=(process.stdout, stdout_buffer), daemon=True
            ),
            threading.Thread(
                target=self._drain_stream, args=(process.stderr, stderr_buffer), daemon=True
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
            # A descendant can escape the process group while retaining these
            # descriptors. Readers therefore get only a bounded grace period.
            for reader in readers:
                reader.join(timeout=0.05)
            for stream in (process.stdout, process.stderr):
                self._release_stream(stream)
            for reader in readers:
                reader.join(timeout=0.05)
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
    def _release_stream(stream) -> None:
        """Soltar el pipe sin quedar preso del lector.

        Un descendiente que escapo del grupo sigue sosteniendo el extremo de
        escritura, asi que el lector queda bloqueado en ``read`` esperando EOF.
        Cerrar el objeto con buffer tomaria el mismo lock que ese lector retiene
        y bloquearia hasta que el descendiente termine -que es exactamente lo que
        el deadline existe para impedir-. Cerrar el descriptor hace que la
        lectura bloqueada falle de inmediato; ``_drain_stream`` ya lo absorbe.
        """
        try:
            os.close(stream.fileno())
        except (OSError, ValueError):
            pass
        try:
            stream.close()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _drain_stream(stream, output: _BoundedOutput) -> None:
        try:
            while chunk := stream.read(64 * 1024):
                output.append(chunk)
        except (OSError, ValueError):
            return

    @classmethod
    def _terminate_process_tree(cls, active: _ActiveProcess) -> None:
        process = active.process
        if os.name == "nt":
            cls._terminate_windows_tree(process)
            return
        process_group = active.process_group
        if process_group is None:
            return
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            return
        end = time.monotonic() + 0.1
        while time.monotonic() < end:
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                break
            time.sleep(0.01)
        try:
            os.killpg(process_group, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()

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
    ) -> ToolResult:
        if role not in allowed:
            return self._denied(role, tool)
        started = time.perf_counter() if started is None else started
        try:
            completed = self._execute_process(args, cwd=cwd, deadline=deadline)
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
            requirements = [self._quality_requirement(module) for module in missing]
            install_options = ["--no-deps"] if (self.root / "requirements.lock").is_file() else []
            result = self._run_python(
                role,
                "install_quality_tools",
                "pip",
                ["install", "--no-input", *install_options, *requirements],
                allowed,
                deadline,
                cwd=environment,
            )
            if result.status is not ToolStatus.SUCCESS:
                return self._operation_failure(result, role, tool)
            self._prepared_tools.update(missing)
            return None
        finally:
            self._mutation_lock.release()

    @staticmethod
    def _quality_requirement(module: str) -> str:
        try:
            return f"{module}=={importlib.metadata.version(module)}"
        except importlib.metadata.PackageNotFoundError:
            requirements = importlib.metadata.requires(_DISTRIBUTION_NAME) or []
            for declared in requirements:
                candidate = declared.split(";", maxsplit=1)[0].strip()
                if candidate == module or (
                    candidate.startswith(module)
                    and len(candidate) > len(module)
                    and candidate[len(module) : len(module) + 1] in "<>=!~"
                ):
                    return candidate
            return module

    def _prepare_project(
        self, role: AgentRole, tool: str, allowed: set[AgentRole], deadline: float
    ) -> ToolResult | None:
        """Install the project, preferring a local hashed lock or constraints file.

        This isolates Python dependencies; it does not sandbox build backends or
        project tests from filesystem and network access.
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
                    role, "install_dependencies", "pip", arguments, allowed, deadline
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
            role, "run_linter", "ruff", ["check", "."], allowed, deadline
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
                "tests,test,test_*.py,*_test.py",
            ],
            allowed,
            deadline,
        )

    def get_security_report(self, role: AgentRole) -> ToolResult:
        return self._get_last(
            role, "get_security_report", "run_security_scan", {AgentRole.SECURITY}
        )
