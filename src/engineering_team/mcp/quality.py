from __future__ import annotations

import ast
import atexit
import importlib.metadata
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.runner import (
    CommandRequest,
    CommandRunner,
    ProcessRunner,
)
from engineering_team.stacks import INTERPRETER, PROFILES, StackProfile

_DISTRIBUTION_NAME = "autonomous-engineering-team"

















def build_runner(root: Path, settings: Settings) -> CommandRunner:
    """Pick the boundary named by configuration, or refuse to guess.

    There is no fallback. A misconfigured runner is a configuration error the
    operator has to see, not something to paper over with the other backend.
    """
    choice = settings.quality_runner
    if choice == "process":
        return ProcessRunner(root)
    if choice == "container":
        image = settings.quality_container_image
        if not image:
            raise ValueError(
                "quality_container_image is required when quality_runner is 'container'"
            )
        return ContainerRunner(root, image=image)
    raise ValueError(f"unknown quality_runner: {choice!r}")


class QualityMCP:
    def __init__(
        self,
        root: str | Path,
        *,
        timeout_seconds: float = 60,
        runner: CommandRunner | None = None,
        settings: Settings | None = None,
        profile: StackProfile | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        # Which ecosystem's commands to run. Python stays the default so every
        # existing caller keeps the behaviour it had before profiles existed.
        self.profile = profile or PROFILES["python"]
        self.timeout_seconds = float(timeout_seconds)
        self._last: dict[str, ToolResult] = {}
        self._project_prepared = False
        self._project_result: ToolResult | None = None
        self._prepared_tools: set[str] = set()
        self._python: str | None = None
        # An explicitly supplied runner always wins. Without settings the process
        # sandbox is used, so constructing a QualityMCP directly does not depend on
        # whatever .env happens to hold on this machine.
        self._runner: CommandRunner = runner or (
            build_runner(self.root, settings) if settings is not None
            else ProcessRunner(self.root)
        )
        self._environment_lock = threading.RLock()
        self._mutation_lock = threading.Lock()
        self._closed = False

    @property
    def _environment(self) -> Path | None:
        """The ephemeral environment, owned by the runner that must grant it."""
        return self._runner.environment

    @_environment.setter
    def _environment(self, value: Path | None) -> None:
        self._runner.environment = value

    def _execute_process(
        self,
        args: list[str],
        *,
        cwd: Path,
        deadline: float,
        allow_network: bool = False,
        allow_subprocesses: bool = False,
        env: tuple[tuple[str, str], ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        """Hand one command to the runner.

        Thin on purpose: quality decides which commands to run, the runner decides
        what they are allowed to touch.
        """
        return self._runner.execute(
            CommandRequest(
                args=tuple(args),
                cwd=cwd,
                deadline=deadline,
                allow_network=allow_network,
                allow_subprocesses=allow_subprocesses,
                env=env,
            )
        )











    def _deadline(self) -> float:
        return time.monotonic() + self.timeout_seconds

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("quality operation deadline exceeded")
        return remaining


    def _interpreter(self, deadline: float | None = None) -> str:
        """Get the interpreter for this instance, provisioning it once."""
        deadline = self._deadline() if deadline is None else deadline
        self._runner.require_available()
        if not self._environment_lock.acquire(timeout=self._remaining(deadline)):
            raise TimeoutError("quality environment lock deadline exceeded")
        try:
            if self._closed or self._runner.closing:
                raise RuntimeError("quality environment is closed")
            if self._python is not None:
                return self._python
            self._python = self._runner.prepare_environment(deadline)
            atexit.register(self.close)
            return self._python
        finally:
            self._environment_lock.release()
    def close(self) -> None:
        """Close the runner, which owns both the processes and the environment."""
        self._runner.close()
        with self._environment_lock:
            if self._closed:
                return
            self._closed = True
            self._python = None
            atexit.unregister(self.close)
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


    def _run_profile(
        self,
        role: AgentRole,
        tool: str,
        phase: str,
        extra: list[str],
        allowed: set[AgentRole],
        deadline: float,
        *,
        cwd: Path | None = None,
        allow_network: bool = False,
    ) -> ToolResult:
        """Run one phase of the component's profile.

        Only a template that names an interpreter provisions one: `mvn test` is
        the command, and building a virtual environment for it would be work
        nobody asked for.
        """
        if role not in allowed:
            return self._denied(role, tool)
        started = time.perf_counter()
        template = getattr(self.profile, f"{phase}_template")
        if template is None:
            return self._operation_failure(
                role, tool,
                f"the {self.profile.name} profile defines no {phase} command",
                started,
            )
        interpreter = ""
        if any(INTERPRETER in part for part in template):
            try:
                interpreter = self._interpreter(deadline)
            except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
                return self._unavailable(role, tool, exc, started)
        environment = str(self._runner.environment or "")
        command = getattr(self.profile, f"{phase}_command")(interpreter, environment)
        # Python installs from a hashed lock and then tests offline. The other
        # toolchains resolve while they build, so denying the network would only
        # make the phase fail; the cache on the shared volume keeps it to the
        # first run. See StackProfile.test_needs_network.
        needs_network = allow_network or (
            phase == "test" and self.profile.test_needs_network
        )
        return self._run(
            role, tool, [*command, *extra], allowed, deadline,
            cwd=cwd or self.root, started=started, allow_network=needs_network,
            env=self.profile.env(environment),
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
        env: tuple[tuple[str, str], ...] = (),
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
                env=env,
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
        # Installing the project and its test tool with pip is Python's answer to
        # a question Maven and dotnet resolve on their own.
        if self.profile.name == "python":
            prepared = self._prepare_project(role, "run_tests", allowed, deadline)
            if prepared is not None:
                return prepared
            prepared = self._prepare_quality_tools(
                role, "run_tests", ("pytest",), allowed, deadline
            )
            if prepared is not None:
                return prepared
        elif self.profile.install_template is not None:
            installed = self._run_profile(
                role, "run_tests", "install", [], allowed, deadline, allow_network=True
            )
            if installed.status is not ToolStatus.SUCCESS:
                return installed
        return self._run_profile(
            role, "run_tests", "test", paths or [], allowed, deadline
        )

    def get_test_results(self, role: AgentRole) -> ToolResult:
        return self._get_last(
            role, "get_test_results", "run_tests", {AgentRole.TESTING}
        )

    def run_build(self, role: AgentRole) -> ToolResult:
        return self._run_profile(
            role, "run_build", "build", [],
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
        extra: list[str] = []
        if self.profile.name == "python":
            prepared = self._prepare_quality_tools(
                role, "run_linter", ("ruff",), allowed, deadline
            )
            if prepared is not None:
                return prepared
            # Ruff resolves configuration by walking up the tree; scoping it to
            # this project is what keeps a nested one from reading outside.
            extra = self._ruff_configuration()
        return self._run_profile(role, "run_linter", "lint", extra, allowed, deadline)

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
