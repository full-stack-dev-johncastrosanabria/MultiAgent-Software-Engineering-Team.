from __future__ import annotations

import ast
import atexit
import importlib.metadata
import json
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engineering_team.components import list_repository_paths, migration_projects
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ErrorCode, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.interpreter import (
    PYTHON_IMAGES,
    describe_install_failure,
    pinned_requirements,
    python_image,
    python_requirement,
    select_interpreter,
)
from engineering_team.mcp.command import CommandRequest, CommandRunner
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.test_evidence import collect_test_cases, snapshot_reports
from engineering_team.stacks import INTERPRETER, StackProfile, profile_for

_DISTRIBUTION_NAME = "autonomous-engineering-team"

















def build_runner(
    root: Path, settings: Settings, *, interpreter: Any = None,
    run_id: str = "", project: str = "",
) -> CommandRunner:
    """Pick the boundary named by configuration, or refuse to guess.

    There is no fallback. A misconfigured runner is a configuration error the
    operator has to see, not something to paper over with the other backend.

    When containers are chosen and no image is named, the image follows the
    project rather than the operator: for the Python stack, an interpreter
    derived from what the project's pins publish (ADR 2, the answer to finding
    11); for every other stack, the pinned image its profile already names
    (ADR 4). An operator who names an image means it, and is not overridden.

    A project that constrains nothing gets the newest interpreter this repository
    ships an image for. ADR 2 refused here, and that refusal was right while the
    process sandbox could still run such a project on the operator's own
    interpreter; with the container as the only boundary it means no gate at all.
    Finding 11 is not reopened: it was a project whose pins did constrain the
    choice, and those still decide. Nothing constraining the choice is not the
    same as the choice being impossible.
    """
    choice = settings.quality_runner
    if choice == "container":
        image = settings.quality_container_image
        if not image:
            if settings.quality_stack == "python":
                chosen = (interpreter or select_interpreter)(root)
                image = python_image(chosen or max(PYTHON_IMAGES))
            else:
                try:
                    image = profile_for(settings.quality_stack).image
                except KeyError as exc:
                    raise ValueError(str(exc)) from exc
        from engineering_team.mcp.run_daemon import RunDaemon

        daemon = (
            RunDaemon(image=settings.quality_run_daemon_image,
                      images=settings.quality_run_daemon_images,
                      run_id=run_id or None, project=project)
            if settings.quality_run_daemon_image else None
        )
        return ContainerRunner(
            root, image=image, daemon=daemon, owns_daemon=daemon is not None,
            run_id=run_id, project=project,
        )
    raise ValueError(f"unknown quality_runner: {choice!r}")


# How a Python project declares what it needs. Detection already treats all of
# these as a Python component; installation knowing a narrower set is what left
# an environment empty and attributed the resulting ModuleNotFoundError to the
# code under test.
PROJECT_MANIFESTS = ("pyproject.toml", "setup.py", "requirements.txt")

# Which provider Surefire runs with is decided by the project's test framework,
# and Surefire resolves it through its own resolver when it executes -- so
# `dependency:go-offline` never sees it and the closed network cannot fetch it.
# ADR 14's trial 2 died exactly there, on `surefire-junit-platform`. Selecting no
# test does not warm it either: Surefire short-circuits before resolving. So the
# providers are fetched by coordinate, and all of them, because guessing which
# one a target project needs is the mistake this avoids. The version is not
# guessed: `surefire-booter` in the cache carries the plugin's own version.
_SUREFIRE_PROVIDERS = (
    "surefire-junit-platform", "surefire-junit47", "surefire-junit4",
    "surefire-testng",
)


def _surefire_providers(environment: str) -> str:
    """Shell that pre-fetches every Surefire provider for the cached version."""
    repository = f"{environment}/m2"
    return (
        f'set -e; for path in {repository}/org/apache/maven/surefire/'
        'surefire-booter/*/; do version=$(basename "$path"); done; '
        f'for provider in {" ".join(_SUREFIRE_PROVIDERS)}; do '
        f'mvn -B -q -Dmaven.repo.local={repository} dependency:get '
        '-Dartifact=org.apache.maven.surefire:$provider:$version; done'
    )


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
        test_filter: str = "",
        run_id: str = "",
        project: str = "",
    ) -> None:
        self.root = Path(root).resolve()
        # Which ecosystem's commands to run. An explicit profile (how every
        # existing caller and test selects one) always wins. Failing that, an
        # explicit, non-auto-detected settings.quality_stack (ADR 4) chooses one.
        # Python stays the default so every caller that predates profiles keeps
        # the behaviour it had.
        if profile is not None:
            self.profile = profile
        else:
            stack = getattr(settings, "quality_stack", None) or "python"
            try:
                self.profile = profile_for(stack)
            except KeyError as exc:
                raise ValueError(str(exc)) from exc
        # Which component these results describe. Empty for a single-component
        # run, which leaves evidence_reference unset exactly as before: the gates
        # group by it, and an unset reference is one bucket.
        self.component = component
        # Which of this component's tests the gate runs. An explicit argument
        # wins over settings, exactly as the profile and the runner do.
        self.test_filter = test_filter or str(
            getattr(settings, "quality_test_filter", "") or ""
        )
        # The dependencies this project declares. They live for the run, so they
        # are started once, before the first phase that could need them.
        self.service_environment: tuple[tuple[str, str], ...] = ()
        self.services = services
        self._services_started = False
        self.timeout_seconds = float(timeout_seconds)
        self._last: dict[str, ToolResult] = {}
        self._project_prepared = False
        self._project_result: ToolResult | None = None
        self._prepared_tools: set[str] = set()
        self._python: str | None = None
        # An explicitly supplied runner always wins. Without one the boundary is
        # whatever configuration names, and configuration names a container by
        # default (ADR 15): there is no second backend left to fall back to.
        # Which run these containers belong to (ADR 16). It reaches the runner
        # and nothing else: a label is bookkeeping, never a boundary.
        self.run_id = run_id
        self.project = project
        self._runner: CommandRunner = runner or build_runner(
            self.root, settings if settings is not None else Settings(),
            run_id=run_id, project=project,
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
                env=tuple({**dict(env), **dict(self.service_environment)}.items()),
                writable_paths=self.profile.toolchain_writable_paths,
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

    # A suite that starts its own containers asks the Docker daemon for them
    # while it runs. Named per ecosystem because the declaration lives in the
    # component's own manifest.
    _CONTAINER_API_MARKERS = (
        ("pom.xml", "org.testcontainers"),
        ("build.gradle", "testcontainers"),
        ("build.gradle.kts", "testcontainers"),
        ("package.json", "testcontainers"),
        ("go.mod", "testcontainers-go"),
    )

    def _container_api_refusal(self) -> RuntimeError | None:
        """Refuse up front when this suite needs a Docker API we cannot offer.

        Inside the quality container there is no route to the daemon, so a
        Testcontainers suite spends the run pulling an image it will never get
        and fails on a `ContainerFetchException` that names neither cause nor
        remedy. It did that three times in one benchmark before anyone read it
        as a boundary rather than a flake. ADR 14 settles where such a suite
        runs -- a daemon owned by the run; saying so before the work starts is
        the whole point.
        """
        if not isinstance(self._runner, ContainerRunner):
            return None
        if self._runner.daemon is not None:
            return None
        for manifest, marker in self._CONTAINER_API_MARKERS:
            path = self.root / manifest
            try:
                declared = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if marker in declared:
                return RuntimeError(
                    f"{self.root.name} declares {marker} in {manifest}, and a "
                    "suite that starts its own containers cannot reach the "
                    "Docker API from inside the quality container. Give this "
                    "run its own daemon: set quality_run_daemon_image to a "
                    "digest-pinned dind image and name the suite's images in "
                    "quality_run_daemon_images (ADR 14). Mounting the host "
                    "socket is refused."
                )
        return None

    def _java_agent_arguments(self, phase: str, environment: str) -> list[str]:
        """Load as agents the jars this toolchain must not attach to itself.

        Only the test phase: nothing else runs the component's own JVM. The jar
        is looked up rather than named so a component that does not depend on it
        is passed nothing, and an ambiguous match is skipped instead of guessed
        at. Note that `-DargLine` sets Surefire's property, so a project that
        configures `argLine` inside the plugin rather than as a property keeps
        its own value and gets no agent -- that stays a visible test failure,
        not a silent one.
        """
        if phase != "test" or not environment or not self.profile.java_agents:
            return []
        cache = Path(environment) / "m2"
        agents: list[str] = []
        for pattern in self.profile.java_agents:
            found = sorted(cache.glob(pattern))
            if len(found) == 1:
                agents.append(f"-javaagent:{found[0]}")
        return [f"-DargLine={' '.join(agents)}"] if agents else []

    def _sandbox_directory(self) -> str:
        """The boundary's writable directory, created first if it does not exist.

        Profiles interpolate this into the command itself -- Maven's
        `repo.local` and HOME, npm's cache -- so it has to exist before the
        command is composed, not when it runs. An empty value would point Maven
        at `/m2` and `HOME=/home`, outside the sandbox entirely.

        `_interpreter` already covers the profiles whose templates name an
        interpreter. Maven and npm name their own binary, so nothing used to
        create this directory for them and every jvm and node component failed
        with `quality environment has not been created` before running anything.
        `CommandRunner` is structural and its test doubles carry a fixed
        directory rather than creating one, so creation is asked for only where
        it is offered.
        """
        prepare = getattr(self._runner, "prepare_scratch", None)
        if prepare is not None and self._runner.environment is None:
            prepare()
        return str(self._runner.environment or "")

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

    def _missing_profile_operation(
        self,
        role: AgentRole,
        tool: str,
        phase: str,
        started: float,
    ) -> ToolResult:
        result = ToolResult(
            tool_name=tool,
            allowed_role=role,
            status=ToolStatus.UNAVAILABLE,
            input_summary="safe",
            output_summary="",
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"the {self.profile.name} profile defines no {phase} command",
            evidence_reference=self._evidence_reference(tool),
        )
        self._last[tool] = result
        return result

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
        return self._apply_schema(role, tool, deadline)

    def _apply_schema(
        self, role: AgentRole, tool: str, deadline: float
    ) -> ToolResult | None:
        """Bring the started database up to the schema the project declares.

        Starting a database creates no tables. Between a service being ready and
        the first test running there is a step ADR 5 never took, and without it a
        project whose schema comes from migrations reports a broken suite rather
        than an unprepared one -- ten of InterviewCleanApi's sixteen tests failed
        on missing tables against a service that had started perfectly.

        It runs here, after the services, because the migration command needs the
        connection string the services just published, and before any phase,
        because every phase after this one assumes the schema is there.
        """
        if not self.profile.schema_template:
            return None
        projects = migration_projects(list_repository_paths(self.root))
        if projects is None:
            return None
        migrations, startup = projects
        started = time.perf_counter()
        try:
            environment = self._sandbox_directory()
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return self._unavailable(role, tool, exc, started)
        for command in self.profile.schema_commands(environment, migrations, startup):
            try:
                completed = self._execute_process(
                    command,
                    cwd=self.root,
                    deadline=deadline,
                    allow_network=True,
                    allow_subprocesses=True,
                    env=self.profile.env(environment),
                )
            except (
                OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired
            ) as exc:
                return self._unavailable(role, tool, exc, started)
            if completed.returncode != 0:
                # A schema that would not apply is infrastructure, not a failing
                # test, and saying so keeps it off the Developer's desk.
                return ToolResult(
                    tool_name=tool,
                    allowed_role=role,
                    status=ToolStatus.UNAVAILABLE,
                    input_summary="schema",
                    output_summary=(completed.stdout + completed.stderr)[-4000:],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    error=(
                        f"{ErrorCode.INFRASTRUCTURE_ERROR.value}: applying the "
                        f"project's migrations failed ({' '.join(command[:3])})"
                    ),
                    evidence_reference=self._evidence_reference(tool),
                )
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
            return self._missing_profile_operation(role, tool, phase, started)
        interpreter = ""
        try:
            if any(INTERPRETER in part for part in template):
                interpreter = self._interpreter(deadline)
            environment = self._sandbox_directory()
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return self._unavailable(role, tool, exc, started)
        command = getattr(self.profile, f"{phase}_command")(interpreter, environment)
        if command is None:
            return self._missing_profile_operation(role, tool, phase, started)
        command = [*command, *self._java_agent_arguments(phase, environment)]
        # Network access belongs to the phase declaration, not to Quality's
        # opinion about a toolchain. The explicit override remains for preparation
        # operations such as npm ci.
        needs_network = allow_network or bool(
            getattr(self.profile, f"{phase}_needs_network", False)
        )
        if phase == "test" and getattr(self._runner, "daemon", None) is not None:
            needs_network = False
            # Resolve dependencies before entering the closed daemon network.
            # None of these commands runs the project's test code: what makes
            # that true is the argument list, not the lifecycle phase named in
            # it, so read them before adding one.
            preparation = {
                "jvm": (
                    ["mvn", "-B", f"-Dmaven.repo.local={environment}/m2",
                     "-DskipTests", "dependency:go-offline", "test-compile"],
                    ["sh", "-c", _surefire_providers(environment)],
                ),
                "dotnet": (["dotnet", "restore",
                            f"-p:RestorePackagesPath={environment}/nuget"],),
                "go": (["go", "mod", "download"],),
            }.get(self.profile.name)
            # Not `command`: that name holds the suite's own command, and
            # rebinding it here made a run report the last preparation step's
            # success as the test phase's, with no test executed (trial 3).
            for preparatory in preparation or ():
                prepared = self._run(
                    role, tool, preparatory, allowed, deadline,
                    cwd=cwd or self.root, allow_network=True,
                    env=self.profile.env(environment),
                )
                if prepared.status is not ToolStatus.SUCCESS:
                    return prepared
        fail_on_output = (
            self._dotnet_reports_vulnerabilities
            if self.profile.name == "dotnet" and phase == "security"
            else None
        )
        unavailable_on_output = (
            self._security_infrastructure_error
            if phase == "security"
            else None
        )
        return self._run(
            role, tool, [*command, *extra], allowed, deadline,
            cwd=cwd or self.root, started=started, allow_network=needs_network,
            env=self.profile.env(environment), fail_on_output=fail_on_output,
            unavailable_on_output=unavailable_on_output,
            scans_dependencies=phase in self.profile.dependency_scan_phases,
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
        fail_on_output: Callable[[str], bool] | None = None,
        unavailable_on_output: Callable[[str], str | None] | None = None,
        scans_dependencies: bool = False,
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
                # Not `allow_network` again: a phase that has to fork does not
                # thereby need the network, and one that is deliberately offline
                # still has to start its own launcher.
                allow_subprocesses=allow_network or self.profile.needs_subprocesses,
                env=env,
            )
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return self._unavailable(role, tool, exc, started)
        full_output = completed.stdout + completed.stderr
        output = full_output[-4000:]
        if completed.returncode < 0:
            return self._unavailable(
                role, tool, RuntimeError("quality subprocess was terminated"), started
            )
        infrastructure_error = (
            unavailable_on_output(full_output)
            if unavailable_on_output is not None
            else None
        )
        if infrastructure_error is not None:
            status = ToolStatus.UNAVAILABLE
        else:
            status = ToolStatus.SUCCESS if completed.returncode == 0 else ToolStatus.FAIL
            if (
                status is ToolStatus.SUCCESS
                and fail_on_output is not None
                and fail_on_output(full_output)
            ):
                status = ToolStatus.FAIL
        result = ToolResult(
            tool_name=tool,
            allowed_role=role,
            status=status,
            input_summary="safe",
            output_summary=output,
            duration_ms=int((time.perf_counter() - started) * 1000),
            evidence_reference=self._evidence_reference(tool),
            error=(
                f"{ErrorCode.INFRASTRUCTURE_ERROR.value}: {infrastructure_error}"
                if infrastructure_error is not None
                else None
            ),
            scans_dependencies=scans_dependencies,
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
            test_cases=previous.test_cases if previous else None,
        )

    def run_tests(self, role: AgentRole, paths: list[str] | None = None) -> ToolResult:
        allowed = {AgentRole.TESTING}
        if role not in allowed:
            return self._denied(role, "run_tests")
        started = time.perf_counter()
        boundary = self._container_api_refusal()
        if boundary is not None:
            return self._unavailable(role, "run_tests", boundary, started)
        if self.test_filter and not self.profile.test_filter_arguments(self.test_filter):
            return self._unavailable(role, "run_tests", RuntimeError(
                f"{self.profile.name} declares no test filter syntax, so "
                f"quality_test_filter={self.test_filter!r} cannot be honoured. "
                "Refusing before the run rather than executing the whole suite "
                "the operator asked to narrow."
            ), started)
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
        report_aware = self.profile.name in {"jvm", "dotnet"}
        before = snapshot_reports(self.root, self.profile.name) if report_aware else {}
        extra = list(paths or [])
        extra.extend(self.profile.test_filter_arguments(self.test_filter))
        if self.profile.name == "dotnet":
            extra.extend(["--logger", "trx"])
        result = self._run_profile(role, "run_tests", "test", extra, allowed, deadline)
        if report_aware:
            result = result.model_copy(update={
                "test_cases": collect_test_cases(self.root, self.profile.name, before)
                if result.status is ToolStatus.SUCCESS else [],
            })
            self._last["run_tests"] = result
        return result

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
        if self.profile.dependency_template is None:
            return self._missing_profile_operation(
                role,
                "scan_dependencies",
                "dependency",
                time.perf_counter(),
            )
        cwd: Path | None = None
        if self.profile.name == "python":
            prepared = self._prepare_project(
                role, "scan_dependencies", allowed, deadline
            )
            if prepared is not None:
                return prepared
            try:
                cwd = Path(self._interpreter(deadline)).parent.parent
            except (
                OSError,
                RuntimeError,
                TimeoutError,
                subprocess.TimeoutExpired,
            ) as exc:
                return self._unavailable(
                    role, "scan_dependencies", exc, time.perf_counter()
                )
        elif self.profile.install_template is not None:
            installed = self._run_profile(
                role,
                "scan_dependencies",
                "install",
                [],
                allowed,
                deadline,
                allow_network=True,
            )
            if installed.status is not ToolStatus.SUCCESS:
                return installed
        return self._run_profile(
            role,
            "scan_dependencies",
            "dependency",
            [],
            allowed,
            deadline,
            cwd=cwd,
        )

    def _ruff_configuration(self) -> list[str]:
        """Acotar la configuracion de ruff al proyecto, no al arbol de arriba.

        Ruff resuelve su configuracion subiendo por los directorios padre. Un
        proyecto anidado dentro de otro repositorio -el caso de los demos- lo
        lleva a leer el pyproject del padre, que queda fuera del sandbox: falla
        con "Failed to read ... Operation not permitted", Security lo reporta
        como herramienta caida y el Reviewer rechaza por un problema que el
        proyecto no tiene.

        El nombre viaja relativo, no absoluto. Ruff lo resuelve contra el
        directorio de trabajo, que es la raiz del componente en cualquiera de
        los dos limites; una ruta del host no existe dentro del contenedor y
        ruff la rechaza con "invalid value for --config", que el Reviewer lee
        igual de mal que el error anterior.
        """
        for name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
            if (self.root / name).is_file():
                return ["--config", name]
        return ["--isolated"]

    def run_security_scan(self, role: AgentRole) -> ToolResult:
        allowed = {AgentRole.SECURITY}
        if role not in allowed:
            return self._denied(role, "run_security_scan")
        deadline = self._deadline()
        if self.profile.security_template is None:
            return self._missing_profile_operation(
                role,
                "run_security_scan",
                "security",
                time.perf_counter(),
            )
        extra: list[str] = []
        if self.profile.name == "python":
            prepared = self._prepare_quality_tools(
                role, "run_security_scan", ("ruff",), allowed, deadline
            )
            if prepared is not None:
                return prepared
            target = (
                "app" if (self.root / "app").is_dir()
                else (
                    "demo-projects/sample_app/app"
                    if (self.root / "demo-projects" / "sample_app" / "app").is_dir()
                    else "."
                )
            )
            extra = [
                target,
                "--select",
                "S",
                "--extend-exclude",
                "tests,test,test_*.py,*_test.py",
                *self._ruff_configuration(),
            ]
        return self._run_profile(
            role,
            "run_security_scan",
            "security",
            extra,
            allowed,
            deadline,
        )

    @staticmethod
    def _dotnet_vulnerability_payload(output: str) -> dict[str, Any] | None:
        """Extract JSON despite harmless MSBuild/NuGet text around the document."""
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", output):
            try:
                payload, _ = decoder.raw_decode(output[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("projects"), list):
                return payload
        return None

    @classmethod
    def _dotnet_reports_vulnerabilities(cls, output: str) -> bool:
        """Interpret the .NET command whose exit code stays zero on findings."""
        payload = cls._dotnet_vulnerability_payload(output)
        if payload is not None:
            pending: list[Any] = [payload]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    vulnerabilities = value.get("vulnerabilities")
                    if isinstance(vulnerabilities, list) and vulnerabilities:
                        return True
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            return False
        lowered = output.lower()
        if "has no vulnerable packages" in lowered:
            return False
        return "has the following vulnerable packages" in lowered

    def _security_infrastructure_error(self, output: str) -> str | None:
        """Separate scanner/advisory outages from findings in target dependencies."""
        indicators = {
            "jvm": (
                "Unable to continue dependency-check analysis",
                "Error updating the NVD Data",
                "NoDataException",
                "NvdApiException",
            ),
            "node": (
                "npm ERR! code EAI_AGAIN",
                "npm ERR! code ECONNREFUSED",
                "npm ERR! code ENETUNREACH",
                "npm ERR! code E401",
                "npm ERR! code E403",
            ),
            "dotnet": (
                "NU1301",
                "Unable to load the service index",
            ),
            "go": (
                "dial tcp:",
                "no such host",
                "module lookup disabled",
            ),
        }
        if any(marker.lower() in output.lower() for marker in indicators.get(
            self.profile.name, ()
        )):
            return f"{self.profile.name} advisory service or scanner was unavailable"
        if (
            self.profile.name == "dotnet"
            and self._dotnet_vulnerability_payload(output) is None
        ):
            return "dotnet vulnerability scanner returned no valid JSON evidence"
        return None

    def get_security_report(self, role: AgentRole) -> ToolResult:
        return self._get_last(
            role, "get_security_report", "run_security_scan", {AgentRole.SECURITY}
        )



class CompositeQuality:
    """One quality handle that runs every component with its own profile.

    ADR 4: a repository is not a stack. Until the graph can record one
    ``run_tests`` result per component, this fans out and aggregates into the
    single ToolResult the Testing node still appends. Commands never cross
    profiles — a Maven module does not see pytest because Python happened to
    be the Settings default.
    """

    transport = "composite"

    def __init__(self, backends: list[Any]) -> None:
        if not backends:
            raise ValueError("CompositeQuality requires at least one backend")
        self._backends = list(backends)
        self.last_component_results: list[ToolResult] = []

    def __enter__(self) -> CompositeQuality:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        for backend in self._backends:
            close = getattr(backend, "close", None)
            if close is not None:
                close()

    @staticmethod
    def _aggregate(tool_name: str, role: AgentRole, results: list[ToolResult]) -> ToolResult:
        if len(results) == 1:
            return results[0]
        status = ToolStatus.SUCCESS
        for result in results:
            if result.status is ToolStatus.UNAVAILABLE:
                status = ToolStatus.UNAVAILABLE
                break
            if result.status is not ToolStatus.SUCCESS and status is ToolStatus.SUCCESS:
                status = result.status
        chunks: list[str] = []
        errors: list[str] = []
        duration = 0
        for result in results:
            label = result.evidence_reference or result.input_summary or result.tool_name
            body = result.output_summary or result.error or result.status.value
            chunks.append(f"{label}: {body}")
            if result.error:
                errors.append(f"{label}: {result.error}")
            duration += int(result.duration_ms or 0)
        return ToolResult(
            tool_name=tool_name,
            allowed_role=role,
            status=status,
            input_summary=f"components={len(results)}",
            output_summary="\n".join(chunks)[-4000:],
            duration_ms=duration,
            evidence_reference=None,
            error="; ".join(errors) if errors else None,
            test_cases=(
                [case for result in results for case in result.test_cases or []]
                if all(result.test_cases is not None for result in results) else None
            ),
        )

    def run_tests(self, role: AgentRole, paths: list[str] | None = None) -> ToolResult:
        results: list[ToolResult] = []
        for backend in self._backends:
            # Pytest path args (`-v`, node ids) belong to the python profile.
            # Forwarding them would turn `mvn test` into `mvn test -v`.
            extra = paths if getattr(backend, "profile", None) is not None and backend.profile.name == "python" else None
            results.append(backend.run_tests(role, extra))
        self.last_component_results = results
        return self._aggregate("run_tests", role, results)

    def get_test_results(self, role: AgentRole) -> ToolResult:
        return self._aggregate(
            "get_test_results",
            role,
            [backend.get_test_results(role) for backend in self._backends],
        )

    def run_build(self, role: AgentRole) -> ToolResult:
        return self._aggregate(
            "run_build",
            role,
            [backend.run_build(role) for backend in self._backends],
        )

    def get_build_status(self, role: AgentRole) -> ToolResult:
        return self._aggregate(
            "get_build_status",
            role,
            [backend.get_build_status(role) for backend in self._backends],
        )

    def run_linter(self, role: AgentRole) -> ToolResult:
        return self._aggregate(
            "run_linter",
            role,
            [backend.run_linter(role) for backend in self._backends],
        )

    def scan_dependencies(self, role: AgentRole) -> ToolResult:
        return self._aggregate(
            "scan_dependencies",
            role,
            [backend.scan_dependencies(role) for backend in self._backends],
        )

    def run_security_scan(self, role: AgentRole) -> ToolResult:
        return self._aggregate(
            "run_security_scan",
            role,
            [backend.run_security_scan(role) for backend in self._backends],
        )

    def get_security_report(self, role: AgentRole) -> ToolResult:
        return self._aggregate(
            "get_security_report",
            role,
            [backend.get_security_report(role) for backend in self._backends],
        )
