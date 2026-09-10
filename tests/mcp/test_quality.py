import importlib.metadata
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.interpreter import python_image
from engineering_team.mcp.client import MCPQualityClient
from engineering_team.mcp.command import CommandRequest
from engineering_team.mcp.container import ENVIRONMENT_MOUNT, ContainerRunner
from engineering_team.mcp.quality import QualityMCP

# Two images, and the difference is deliberate. A test that patches `execute`
# never starts a container, so the digest only has to satisfy the runner's
# refusal to accept an unpinned name. A test that runs commands for real needs
# an image that exists, and takes the same one the interpreter selection would
# have derived.
PINNED = "python@sha256:" + "0" * 64
REAL = python_image((3, 13))


def _quality(root: Path, *, image: str = PINNED, **kwargs) -> QualityMCP:
    """A gate on the boundary the gate actually uses.

    QualityMCP takes the runner it is given. Naming it here rather than letting
    the constructor pick keeps the choice of boundary a decision the test makes,
    which is the same rule production follows.
    """
    kwargs.setdefault("runner", ContainerRunner(root, image=image))
    return QualityMCP(root, **kwargs)


def _patch_executor(monkeypatch, callback) -> None:
    """Intercept at the runner, which is where every command converges.

    Environment provisioning goes straight through the runner rather than back
    up through QualityMCP, so patching the runner is what sees the whole
    sequence: venv, ensurepip, installs and the tool itself. The callback keeps
    the keyword shape it had when the process sandbox was the boundary; what
    changed is which runner is asked, not what the gate asks it.
    """

    def execute(runner, request: CommandRequest):
        return callback(
            list(request.args),
            cwd=request.cwd,
            deadline=request.deadline,
            allow_network=request.allow_network,
            allow_subprocesses=request.allow_subprocesses,
            env=dict(request.env),
            timeout=max(0.0, request.deadline - time.monotonic()),
        )

    monkeypatch.setattr(ContainerRunner, "execute", execute)


def _base_python() -> str:
    """The interpreter the venv is built from, named as the boundary sees it.

    The process sandbox resolved the host's base executable so a venv could not
    be layered on another venv. A container has one interpreter and it is on
    PATH, so the same property needs no resolution: `python` is the image's,
    and there is no operator runtime to pick up by accident.
    """
    return "python"


def test_quality_mcp_preserves_failed_test_result(tmp_path: Path) -> None:
    (tmp_path / "test_failure.py").write_text(
        "def test_fails():\n    assert False\n", encoding="utf-8"
    )
    result = _quality(tmp_path, image=REAL).run_tests(AgentRole.TESTING, ["test_failure.py"])

    assert result.status is ToolStatus.FAIL
    assert "failed" in result.output_summary.lower()


def test_quality_mcp_is_deny_by_default_for_every_operation(tmp_path: Path) -> None:
    mcp = _quality(tmp_path)
    operations = {
        "run_tests": ({AgentRole.TESTING}, lambda role: mcp.run_tests(role, [])),
        "get_test_results": ({AgentRole.TESTING}, mcp.get_test_results),
        "run_build": ({AgentRole.DEVELOPER, AgentRole.TESTING}, mcp.run_build),
        "get_build_status": (
            {AgentRole.DEVELOPER, AgentRole.TESTING}, mcp.get_build_status
        ),
        "run_linter": ({AgentRole.DEVELOPER, AgentRole.TESTING}, mcp.run_linter),
        "scan_dependencies": ({AgentRole.SECURITY}, mcp.scan_dependencies),
        "run_security_scan": ({AgentRole.SECURITY}, mcp.run_security_scan),
        "get_security_report": ({AgentRole.SECURITY}, mcp.get_security_report),
    }
    for name, (allowed, operation) in operations.items():
        for role in AgentRole:
            if role not in allowed:
                result = operation(role)
                assert result.status is ToolStatus.DENIED
                assert result.tool_name == name


def test_denied_quality_operation_never_starts_subprocess(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("subprocess must not execute for a denied role")

    _patch_executor(monkeypatch, forbidden)
    result = _quality(tmp_path).scan_dependencies(AgentRole.PRODUCT)
    assert result.status is ToolStatus.DENIED


def test_quality_getter_preserves_last_real_result(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    mcp = _quality(tmp_path, image=REAL)
    executed = mcp.run_tests(AgentRole.TESTING, ["test_ok.py"])
    retrieved = mcp.get_test_results(AgentRole.TESTING)

    assert executed.status is ToolStatus.SUCCESS
    assert retrieved.status is ToolStatus.SUCCESS
    assert "passed" in retrieved.output_summary.lower()


def test_quality_installs_declared_project_dependencies_once_before_pytest(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\ndependencies = ['example-dependency']\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, run)
    quality = _quality(tmp_path)

    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS
    assert len(calls) == 6
    assert calls[0][:5] == [_base_python(), "-I", "-m", "venv", "--without-pip"]
    isolated_python = calls[1][0]
    assert isolated_python != sys.executable
    assert calls[1:] == [
        [isolated_python, "-I", "-m", "ensurepip", "--upgrade"],
        [isolated_python, "-I", "-m", "pip", "install", "--no-input", "."],
        [
            isolated_python,
            "-I",
            "-m",
            "pip",
            "install",
            "--no-input",
            "--no-deps",
            *QualityMCP._quality_toolchain_requirements(),
        ],
        [isolated_python, "-I", "-m", "pytest"],
        [isolated_python, "-I", "-m", "pytest"],
    ]


def test_quality_installs_dependencies_outside_the_shared_interpreter(
    tmp_path: Path, monkeypatch
) -> None:
    """Finding 3: `pip install .` corria con sys.executable, asi que las
    dependencias del proyecto destino quedaban en el venv de ASET, disponibles
    para las corridas siguientes y mutables en paralelo."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\ndependencies = ['example-dependency']\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    _patch_executor(
        monkeypatch,
        lambda args, **kw: (calls.append(args), subprocess.CompletedProcess(args, 0, "", ""))[1],
    )
    quality = _quality(tmp_path)

    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS

    project_calls = calls[1:]
    interpreters = {call[0] for call in project_calls}
    assert interpreters, "no se ejecuto ningun comando"
    assert sys.executable not in interpreters, (
        "el interprete compartido sigue recibiendo los comandos del proyecto"
    )
    assert len(interpreters) == 1, "el run deberia usar un unico interprete aislado"
    assert any("pip" in call and "install" in call for call in project_calls)




def test_quality_project_is_installed_even_without_runtime_dependencies(
    tmp_path: Path, monkeypatch
) -> None:
    """A src-layout project must be importable without an unsafe PYTHONPATH."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n", encoding="utf-8"
    )
    calls: list[list[str]] = []
    _patch_executor(
        monkeypatch,
        lambda args, **kw: (calls.append(args), subprocess.CompletedProcess(args, 0, "", ""))[1],
    )

    quality = _quality(tmp_path)
    quality.run_tests(AgentRole.TESTING)

    assert any("install" in call and call[-1] == "." for call in calls)
    assert calls[1][0] != sys.executable


def test_denied_quality_operations_never_create_an_environment(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\ndependencies = ['dependency']\n",
        encoding="utf-8",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("a denied operation must not create an environment or subprocess")

    _patch_executor(monkeypatch, forbidden)
    quality = _quality(tmp_path)

    assert quality.run_tests(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.run_build(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.run_linter(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.scan_dependencies(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.run_security_scan(AgentRole.PRODUCT).status is ToolStatus.DENIED




def test_quality_environment_creation_is_thread_safe(tmp_path: Path, monkeypatch) -> None:
    created: list[list[str]] = []

    def execute(args, **kwargs):
        if args[:4] == [_base_python(), "-I", "-m", "venv"]:
            created.append(args)
            time.sleep(0.05)
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, execute)
    quality = _quality(tmp_path)
    interpreters: list[str] = []
    threads = [
        threading.Thread(target=lambda: interpreters.append(quality._interpreter()))
        for _ in range(4)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len(created) == 1
        assert len(set(interpreters)) == 1
    finally:
        quality.close()


def test_quality_environment_does_not_inherit_shared_site_packages(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[list[str]] = []
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: (
            calls.append(args),
            subprocess.CompletedProcess(args, 0, "", ""),
        )[1],
    )
    quality = _quality(tmp_path)

    try:
        quality._interpreter()
        assert calls[0][:5] == [
            _base_python(), "-I", "-m", "venv", "--without-pip",
        ]
        assert "--system-site-packages" not in calls[0]
    finally:
        quality.close()




def test_quality_close_removes_environment_and_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    runner = ContainerRunner(tmp_path, image=PINNED)
    quality = _quality(tmp_path, runner=runner)
    environment = Path(quality._interpreter()).parent.parent

    # The environment is a volume the runner owns, mounted at a fixed path, so
    # what closing has to guarantee is that no further work reaches it -- not
    # that a host directory disappeared, which is how the process sandbox
    # released it.
    assert environment == Path(ENVIRONMENT_MOUNT)
    assert not runner.closing
    quality.close()
    quality.close()

    assert runner.closing
    assert not tmp_path.joinpath("aset-env").exists()


def test_quality_reports_environment_bootstrap_failure_as_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    def fail(*args, **kwargs):
        raise OSError("cannot create isolated environment")

    _patch_executor(monkeypatch, fail)

    result = _quality(tmp_path).run_build(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert result.tool_name == "run_build"
    assert "isolated environment" in (result.error or "")


def test_all_quality_commands_use_the_same_isolated_environment(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[list[str]] = []
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: (
            calls.append(args),
            subprocess.CompletedProcess(args, 0, "", ""),
        )[1],
    )
    quality = _quality(tmp_path)

    assert quality.run_build(AgentRole.TESTING).status is ToolStatus.SUCCESS
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS
    assert quality.run_linter(AgentRole.TESTING).status is ToolStatus.SUCCESS
    assert quality.scan_dependencies(AgentRole.SECURITY).status is ToolStatus.SUCCESS
    assert quality.run_security_scan(AgentRole.SECURITY).status is ToolStatus.SUCCESS

    try:
        interpreter = quality._interpreter()
        assert calls
        environment_calls = calls[1:]
        assert all(call[0] == interpreter for call in environment_calls)
        assert all(call[1:3] == ["-I", "-m"] for call in environment_calls)
        assert {call[3] for call in environment_calls} >= {
            "compileall", "pip", "pytest", "ruff",
        }
    finally:
        quality.close()


def test_concurrent_tests_wait_for_dependency_installation(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\ndependencies = ['dependency']\n",
        encoding="utf-8",
    )
    install_started = threading.Event()
    release_install = threading.Event()
    pytest_started = threading.Event()
    project_installs = 0
    call_lock = threading.Lock()

    def run(args, **kwargs):
        nonlocal project_installs
        if args[-1] == "." and "install" in args:
            with call_lock:
                project_installs += 1
            install_started.set()
            release_install.wait(timeout=2)
        elif "pytest" in args:
            pytest_started.set()
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, run)
    quality = _quality(tmp_path)
    results: list[ToolResult] = []
    first = threading.Thread(
        target=lambda: results.append(quality.run_tests(AgentRole.TESTING))
    )
    second = threading.Thread(
        target=lambda: results.append(quality.run_tests(AgentRole.TESTING))
    )

    first.start()
    assert install_started.wait(timeout=1)
    second.start()
    assert not pytest_started.wait(timeout=0.1)
    release_install.set()
    first.join(timeout=2)
    second.join(timeout=2)

    try:
        assert not first.is_alive()
        assert not second.is_alive()
        assert project_installs == 1
        assert len(results) == 2
        assert all(result.status is ToolStatus.SUCCESS for result in results)
    finally:
        quality.close()




def test_project_and_tool_installs_share_one_mutation_lock(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\ndependencies = ['dependency']\n",
        encoding="utf-8",
    )
    project_install_started = threading.Event()
    release_project_install = threading.Event()
    overlapping_install = threading.Event()

    def run(args, **kwargs):
        is_install = "pip" in args and "install" in args
        if is_install and args[-1] == ".":
            project_install_started.set()
            release_project_install.wait(timeout=2)
        elif is_install and not release_project_install.is_set():
            overlapping_install.set()
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, run)
    quality = _quality(tmp_path)
    test_thread = threading.Thread(target=lambda: quality.run_tests(AgentRole.TESTING))
    lint_thread = threading.Thread(target=lambda: quality.run_linter(AgentRole.TESTING))

    test_thread.start()
    assert project_install_started.wait(timeout=1)
    lint_thread.start()
    overlapping_install.wait(timeout=0.1)
    release_project_install.set()
    test_thread.join(timeout=2)
    lint_thread.join(timeout=2)

    try:
        assert not overlapping_install.is_set()
    finally:
        quality.close()


def test_quality_uses_one_end_to_end_deadline_across_setup_phases(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\ndependencies = ['dependency']\n",
        encoding="utf-8",
    )
    received_timeouts: list[float] = []

    def run(args, **kwargs):
        timeout = float(kwargs["timeout"])
        received_timeouts.append(timeout)
        time.sleep(0.03)
        if timeout < 0.03:
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, run)
    quality = _quality(tmp_path, timeout_seconds=0.07)
    started = time.perf_counter()

    result = quality.run_tests(AgentRole.TESTING)

    try:
        assert result.status is ToolStatus.UNAVAILABLE
        assert time.perf_counter() - started < 0.13
        assert received_timeouts == sorted(received_timeouts, reverse=True)
        assert received_timeouts[-1] < received_timeouts[0]
    finally:
        quality.close()


def test_quality_prefers_hashed_lock_and_installs_project_without_deps(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n", encoding="utf-8"
    )
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "dependency==1.0 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8"
    )
    calls: list[list[str]] = []
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: (
            calls.append(args),
            subprocess.CompletedProcess(args, 0, "", ""),
        )[1],
    )
    quality = _quality(tmp_path)

    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS

    try:
        pip_installs = [call for call in calls if "pip" in call and "install" in call]
        # The name, not the path: both runners set cwd to the project root, and
        # an absolute host path names nothing inside a container.
        assert ["--require-hashes", "--no-build-isolation", "-r", lock.name] == (
            pip_installs[0][-4:]
        )
        assert pip_installs[1][-4:] == [
            "--no-input", "--no-deps", "--no-build-isolation", ".",
        ]
    finally:
        quality.close()


def test_real_project_modules_cannot_shadow_quality_toolchain(tmp_path: Path) -> None:
    (tmp_path / "src" / "demo_pkg").mkdir(parents=True)
    (tmp_path / "src" / "demo_pkg" / "__init__.py").write_text(
        "VALUE = 42\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[build-system]\n"
        "requires = ['setuptools>=68']\n"
        "build-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'demo-shadowing'\nversion = '0.1.0'\n"
        "[tool.setuptools.packages.find]\nwhere = ['src']\n",
        encoding="utf-8",
    )
    (tmp_path / "test_import.py").write_text(
        "from demo_pkg import VALUE\n\n\ndef test_import():\n    assert VALUE == 42\n",
        encoding="utf-8",
    )
    sentinel = tmp_path / "toolchain-shadowed"
    shadow = (
        "from pathlib import Path\n\n"
        f"Path({str(sentinel)!r}).write_text('shadowed', encoding='utf-8')\n"
    )
    for module in ("pip", "pytest", "ruff", "compileall"):
        (tmp_path / f"{module}.py").write_text(shadow, encoding="utf-8")
    quality = _quality(tmp_path, image=REAL, timeout_seconds=60)

    try:
        tested = quality.run_tests(AgentRole.TESTING, ["test_import.py"])
        built = quality.run_build(AgentRole.TESTING)
        linted = quality.run_linter(AgentRole.TESTING)

        assert tested.status is ToolStatus.SUCCESS, tested.error or tested.output_summary
        assert built.status is ToolStatus.SUCCESS, built.error or built.output_summary
        assert linted.status is ToolStatus.SUCCESS, linted.error or linted.output_summary
        assert not sentinel.exists()
    finally:
        quality.close()












def test_mutation_lock_wait_is_inside_operation_deadline(tmp_path: Path, monkeypatch) -> None:
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    quality = _quality(tmp_path, timeout_seconds=0.05)
    quality._mutation_lock.acquire()
    release = threading.Timer(0.2, quality._mutation_lock.release)
    release.start()
    started = time.monotonic()

    result = quality.run_linter(AgentRole.TESTING)

    try:
        assert result.status is ToolStatus.UNAVAILABLE
        assert time.monotonic() - started < 0.12
    finally:
        release.join(timeout=1)
        quality.close()


def test_environment_lock_wait_is_inside_operation_deadline(tmp_path: Path) -> None:
    quality = _quality(tmp_path, timeout_seconds=0.05)
    locked = threading.Event()
    release = threading.Event()

    def hold_environment_lock() -> None:
        with quality._environment_lock:
            locked.set()
            release.wait(timeout=1)

    holder = threading.Thread(target=hold_environment_lock)
    holder.start()
    assert locked.wait(timeout=1)
    started = time.monotonic()

    result = quality.run_build(AgentRole.TESTING)

    try:
        assert result.status is ToolStatus.UNAVAILABLE
        assert time.monotonic() - started < 0.12
    finally:
        release.set()
        holder.join(timeout=1)
        quality.close()


def test_venv_creation_is_an_interruptible_isolated_subprocess(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[list[str]] = []
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: (
            calls.append(args),
            subprocess.CompletedProcess(args, 0, "", ""),
        )[1],
    )
    quality = _quality(tmp_path)

    try:
        quality._interpreter()
        assert calls[0][:5] == [
            _base_python(), "-I", "-m", "venv", "--without-pip",
        ]
        assert calls[1][1:4] == ["-I", "-m", "ensurepip"]
    finally:
        quality.close()






def test_quality_tools_install_uses_the_complete_declared_lock(tmp_path: Path) -> None:
    """HIGH: --no-deps is safe only with the complete declared toolchain closure."""
    (tmp_path / "requirements.lock").write_text(
        "example==1.0 --hash=sha256:0\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0.1.0'\ndependencies=['example']\n", encoding="utf-8"
    )
    calls: list[list[str]] = []
    quality = _quality(tmp_path, image=REAL, timeout_seconds=10)

    def record(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    quality._execute_process = record
    try:
        quality.run_tests(AgentRole.TESTING)
    finally:
        quality.close()

    tool_installs = [
        call for call in calls
        if "install" in call
        and any(part.startswith(("pytest==", "ruff==")) for part in call)
    ]
    assert tool_installs, "no se instalaron las herramientas de calidad"
    for call in tool_installs:
        assert "--no-deps" in call
        assert set(QualityMCP._quality_toolchain_requirements()) <= set(call)




def test_missing_workspace_is_reported_without_starting_a_server(tmp_path: Path) -> None:
    """La guarda de workspace inexistente no tenia cobertura."""
    client = MCPQualityClient(tmp_path / "does-not-exist", timeout_seconds=5)
    started = time.monotonic()

    result = client.run_tests(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "MissingWorkspace" in (result.error or "")
    assert time.monotonic() - started < 0.5, "levanto el subproceso antes de rechazar"
    assert client._thread is None








@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin TLS sandbox regression")
def test_install_phase_can_download_over_real_pypi_tls(tmp_path: Path) -> None:
    quality = _quality(tmp_path, image=REAL, timeout_seconds=30)
    try:
        interpreter = quality._interpreter()
        environment = Path(interpreter).parent.parent
        completed = quality._execute_process(
            [
                interpreter,
                "-I",
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--dest",
                str(environment / "tmp"),
                "pytest==8.4.2",
            ],
            cwd=environment,
            deadline=time.monotonic() + 25,
            allow_network=True,
            allow_subprocesses=True,
        )

        assert completed.returncode == 0, completed.stderr
    finally:
        quality.close()


def test_quality_tool_requirements_come_from_exact_project_declarations(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "999.999")
    quality = _quality(tmp_path, image=REAL)

    assert quality._quality_requirement("pytest") == "pytest==8.4.2"
    assert quality._quality_requirement("ruff") == "ruff==0.16.5"


def test_quality_toolchain_closure_resolves_markers_for_supported_pythons() -> None:
    py310 = set(QualityMCP._resolved_quality_toolchain((3, 10), "darwin"))
    py312 = set(QualityMCP._resolved_quality_toolchain((3, 12), "linux"))
    windows310 = set(QualityMCP._resolved_quality_toolchain((3, 10), "win32"))

    assert "exceptiongroup==1.3.0" in py310
    assert "tomli==2.2.1" in py310
    assert "typing-extensions==4.16.0" in py310
    assert "exceptiongroup==1.3.0" not in py312
    assert "tomli==2.2.1" not in py312
    assert "typing-extensions==4.16.0" in py312
    assert "colorama==0.4.6" in windows310


def test_wheel_metadata_fallback_preserves_and_evaluates_markers(monkeypatch) -> None:
    monkeypatch.setattr(
        QualityMCP,
        "_source_quality_toolchain",
        staticmethod(lambda: ()),
        raising=False,
    )
    monkeypatch.setattr(
        importlib.metadata,
        "requires",
        lambda _name: [
            (
                "wheel-only==1.0; python_version < '3.11' and "
                "extra == 'quality-toolchain'"
            ),
            (
                "windows-only==2.0; sys_platform == 'win32' and "
                "extra == 'quality-toolchain'"
            ),
            "ignored==3.0; extra == 'dev'",
        ],
    )

    declared = QualityMCP._quality_toolchain_requirements()
    py310 = QualityMCP._resolved_quality_toolchain((3, 10), "darwin")
    py312_windows = QualityMCP._resolved_quality_toolchain((3, 12), "win32")

    assert "wheel-only==1.0; python_version < '3.11'" in declared
    assert "windows-only==2.0; sys_platform == 'win32'" in declared
    assert all("extra" not in requirement for requirement in declared)
    assert py310 == ("wheel-only==1.0",)
    assert py312_windows == ("windows-only==2.0",)




















def test_only_pip_install_subprocesses_receive_network_access(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )
    calls: list[tuple[list[str], bool]] = []

    def record(args, **kwargs):
        calls.append((list(args), bool(kwargs["allow_network"])))
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, record)
    quality = _quality(tmp_path)
    try:
        assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS
    finally:
        quality.close()

    assert calls
    for command, network in calls:
        is_install = "pip" in command and "install" in command
        assert network is is_install, (command, network)










def test_quality_container_contract_is_documented() -> None:
    operations = (Path(__file__).parents[2] / "docs/operations.md").read_text(encoding="utf-8")

    assert "[QualityMCP](../src/engineering_team/mcp/quality.py)" in operations
    assert "QUALITY_RUNNER=container" in operations
    assert "[Settings](../src/engineering_team/config.py)" in operations


def test_ruff_config_stays_inside_the_sandboxed_project(tmp_path: Path) -> None:
    """Los demos viven dentro del repo padre. Ruff busca su configuracion
    subiendo por el arbol, llega al pyproject del padre -fuera del sandbox- y
    falla, y el Reviewer termina rechazando por 'security tooling'."""
    parent = tmp_path / "monorepo"
    project = parent / "sub" / "demo"
    project.mkdir(parents=True)
    (parent / "pyproject.toml").write_text(
        "[project]\nname='parent'\nversion='0.1.0'\n", encoding="utf-8"
    )
    (project / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )
    (project / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    quality = _quality(project, image=REAL, timeout_seconds=180)
    try:
        linted = quality.run_linter(AgentRole.DEVELOPER)
        scanned = quality.run_security_scan(AgentRole.SECURITY)
    finally:
        quality.close()

    for result in (linted, scanned):
        combined = (result.output_summary or "") + (result.error or "")
        assert "Failed to read" not in combined, combined[:200]
        assert result.status is not ToolStatus.UNAVAILABLE
