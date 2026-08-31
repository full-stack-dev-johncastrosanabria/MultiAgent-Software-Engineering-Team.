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
from typing import Any

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ErrorCode, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.interpreter import (
    describe_install_failure,
    pinned_requirements,
    python_image,
    python_requirement,
    select_interpreter,
)
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.runner import (
    CommandRequest,
    CommandRunner,
    ProcessRunner,
)
from engineering_team.stacks import INTERPRETER, PROFILES, StackProfile

_DISTRIBUTION_NAME = "autonomous-engineering-team"

















def build_runner(
    root: Path, settings: Settings, *, interpreter: Any = None
) -> CommandRunner:
    """Pick the boundary named by configuration, or refuse to guess.

    There is no fallback. A misconfigured runner is a configuration error the
    operator has to see, not something to paper over with the other backend.

    When containers are chosen and no image is named, the image follows the
    project rather than the operator: an interpreter derived from what the
    project's pins publish, which is the whole point of ADR 2 and the answer to
    finding 11. An operator who names an image means it, and is not overridden.
    """
    choice = settings.quality_runner
    if choice == "process":
        return ProcessRunner(root)
    if choice == "container":
        image = settings.quality_container_image
        if not image:
            chosen = (interpreter or select_interpreter)(root)
            if chosen is None:
                raise ValueError(
                    "no container image is configured and none could be derived "
                    "from this project; set quality_container_image"
                )
            image = python_image(chosen)
        return ContainerRunner(root, image=image)
    raise ValueError(f"unknown quality_runner: {choice!r}")


# How a Python project declares what it needs. Detection already treats all of
# these as a Python component; installation knowing a narrower set is what left
# an environment empty and attributed the resulting ModuleNotFoundError to the
# code under test.
PROJECT_MANIFESTS = ("pyproject.toml", "setup.py", "requirements.txt")


class QualityMCP:
    def __init__(
        self,
        root: str | Path,
        *,
        timeout_seconds: float = 60,
        runner: CommandRunner | None = None,
        settings: Settings | None = None,
        profile: StackProfile | None = None,
        component: str = "",
        services: Any = None,
    ) -> None:
        self.root = Path(root).resolve()
        # Which ecosystem's commands to run. Python stays the default so every
        # existing caller keeps the behaviour it had before profiles existed.
        self.profile = profile or PROFILES["python"]
        # Which component these results describe. Empty for a single-component
        # run, which leaves evidence_reference unset exactly as before: the gates
        # group by it, and an unset reference is one bucket.
        self.component = component
        # The dependencies this project declares. They live for the run, so they
        # are started once, before the first phase that could need them.
        self.services = services
        self._services_started = False
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

    def _evidence_reference(self, tool: str) -> str | None:
        """Identify the component a result came from, when there is one."""
        return f"mcp://quality/{tool}#{self.component}" if self.component else None

    def _denied(self, role: AgentRole, tool: str) -> ToolResult:
        return ToolResult(
            tool_name=tool, allowed_role=role, status=ToolStatus.DENIED,
            input_summary="denied", output_summary="", duration_ms=0, error="role denied",
            evidence_reference=self._evidence_reference(tool),
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
            evidence_reference=self._evidence_reference(tool),
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



    def _ensure_services(
        self, role: AgentRole, tool: str, deadline: float
    ) -> ToolResult | None:
        """Start the project's dependencies, or report why they are missing.

        A service that never became ready is not a failing test. Letting the
        suite run and fail would attribute an infrastructure problem to the code
        under test -- the misleading headline finding 7 describes -- so the run
        stops here and says which it was.
        """
        if self.services is None or self._services_started:
            return None
        if not getattr(self.services, "services", ()):
            self._services_started = True
            return None
        started = time.perf_counter()
        try:
            self.services.up(deadline)
        except (OSError, RuntimeError, subprocess.SubprocessError, TimeoutError) as exc:
            return ToolResult(
                tool_name=tool, allowed_role=role, status=ToolStatus.UNAVAILABLE,
                input_summary="services", output_summary="",
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"{ErrorCode.INFRASTRUCTURE_ERROR.value}: {exc}",
                evidence_reference=self._evidence_reference(tool),
            )
        self._services_started = True
        network = getattr(self.services, "network", None)
        if network and hasattr(self._runner, "network"):
            # The commands have to join the network the services are on, and it
            # only exists once they are up.
            self._runner.network = network
        return None

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
            evidence_reference=self._evidence_reference(tool),
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
            installable = self.root / "pyproject.toml"
            requirements = self.root / "requirements.txt"
            if not installable.is_file() and not (self.root / "setup.py").is_file():
                if not requirements.is_file():
                    self._project_prepared = True
                    return None
                # No build backend to install *from*, but the dependencies are
                # declared and the tests cannot import anything without them.
                self._project_prepared = True
                return self._install_requirements(role, tool, requirements, deadline)
            # Relative names, not absolute paths. Both runners execute with
            # cwd set to the project root, and an absolute host path inside a
            # container names a file that is not there -- measured as "Could
            # not open requirements file: /private/tmp/.../requirements.txt".
            lock = self.root / "requirements.lock"
            constraints = self.root / "constraints.txt"
            if lock.is_file():
                commands = [
                    [
                        "install", "--no-input", "--require-hashes",
                        "--no-build-isolation", "-r", lock.name,
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
                        "--constraint", constraints.name, ".",
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


    def _install_requirements(
        self, role: AgentRole, tool: str, requirements: Path, deadline: float
    ) -> ToolResult | None:
        """Install a project that declares dependencies but ships no backend.

        The overwhelmingly common shape of a Python application: a
        requirements.txt and no packaging metadata. Nothing is installed *as* a
        package, only what it says it needs, and the network is open for this
        phase alone.
        """
        completed = self._run_python(
            role, tool, "pip",
            ["install", "--no-input", "-r", requirements.name],
            {role}, deadline, cwd=self.root, allow_network=True,
        )
        if completed.status is ToolStatus.SUCCESS:
            return None
        # Say what actually went wrong. A wheel-less dependency compiled from
        # source produces a wall of ninja output, and reporting that verbatim
        # sends the operator -- and the Reviewer -- after the project's code.
        text = requirements.read_text(encoding="utf-8", errors="replace")
        explanation = describe_install_failure(
            completed.output_summary + (completed.error or ""),
            interpreter=self._environment_version(),
            requirement=python_requirement(self._declaration_sources()),
            pins=pinned_requirements(text),
        )
        if explanation is not None:
            completed = completed.model_copy(update={
                "status": ToolStatus.UNAVAILABLE,
                "error": f"{ErrorCode.INFRASTRUCTURE_ERROR.value}: {explanation}",
            })
        self._project_result = completed
        return self._operation_failure(completed, role, tool)

    def _environment_version(self) -> tuple[int, int]:
        """The interpreter the ephemeral environment was actually built from."""
        return (sys.version_info.major, sys.version_info.minor)

    def _declaration_sources(self) -> dict[str, str]:
        """The few files where a project states which Python it needs."""
        sources: dict[str, str] = {}
        for name in (
            "pyproject.toml", "setup.py", "setup.cfg", ".python-version",
            "Dockerfile", "backend/Dockerfile",
        ):
            candidate = self.root / name
            if candidate.is_file():
                try:
                    sources[name] = candidate.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    continue
        return sources

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
        unavailable = self._ensure_services(role, "run_tests", deadline)
        if unavailable is not None:
            return unavailable
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
