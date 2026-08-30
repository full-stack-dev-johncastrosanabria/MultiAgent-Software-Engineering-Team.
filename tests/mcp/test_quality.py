import importlib.metadata
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import engineering_team.mcp.runner as runner_module
from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.mcp.client import MCPQualityClient
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.runner import (
    _VENV_BIN,
    ProcessRunner,
    _BoundedOutput,
    _system_path_entries,
)


def _patch_executor(monkeypatch, callback) -> None:
    """Intercept at the runner, which is where every command now converges.

    Environment provisioning goes straight through the runner rather than back
    up through QualityMCP, so patching the runner is what sees the whole
    sequence: venv, ensurepip, installs and the tool itself.
    """

    def execute(
        runner,
        args,
        *,
        cwd,
        deadline,
        allow_network=False,
        allow_subprocesses=False,
    ):
        return callback(
            args,
            cwd=cwd,
            deadline=deadline,
            allow_network=allow_network,
            allow_subprocesses=allow_subprocesses,
            env=runner._subprocess_environment(),
            timeout=max(0.0, deadline - time.monotonic()),
        )

    monkeypatch.setattr(ProcessRunner, "_execute_process", execute)


def _base_python() -> str:
    return str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())


def test_quality_mcp_preserves_failed_test_result(tmp_path: Path) -> None:
    (tmp_path / "test_failure.py").write_text(
        "def test_fails():\n    assert False\n", encoding="utf-8"
    )
    result = QualityMCP(tmp_path).run_tests(AgentRole.TESTING, ["test_failure.py"])

    assert result.status is ToolStatus.FAIL
    assert "failed" in result.output_summary.lower()


def test_quality_mcp_is_deny_by_default_for_every_operation(tmp_path: Path) -> None:
    mcp = QualityMCP(tmp_path)
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
    result = QualityMCP(tmp_path).scan_dependencies(AgentRole.PRODUCT)
    assert result.status is ToolStatus.DENIED


def test_quality_getter_preserves_last_real_result(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    mcp = QualityMCP(tmp_path)
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
    quality = QualityMCP(tmp_path)

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
    quality = QualityMCP(tmp_path)

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


def test_quality_environment_never_lands_inside_the_project(tmp_path: Path) -> None:
    """El root puede ser el proyecto REAL del usuario (apply_run.py:56), no una
    copia: el entorno efimero no puede crearse ahi ni aparecer en los listados."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\ndependencies = ['example-dependency']\n",
        encoding="utf-8",
    )
    before = set(tmp_path.iterdir())
    quality = QualityMCP(tmp_path)

    interpreter = Path(quality._interpreter())

    assert tmp_path not in interpreter.parents, "el entorno se creo dentro del proyecto"
    assert set(tmp_path.iterdir()) == before, "el proyecto gano archivos nuevos"


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

    quality = QualityMCP(tmp_path)
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
    quality = QualityMCP(tmp_path)

    assert quality.run_tests(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.run_build(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.run_linter(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.scan_dependencies(AgentRole.PRODUCT).status is ToolStatus.DENIED
    assert quality.run_security_scan(AgentRole.PRODUCT).status is ToolStatus.DENIED


def test_quality_instances_have_distinct_environments(tmp_path: Path) -> None:
    first = QualityMCP(tmp_path)
    second = QualityMCP(tmp_path)

    try:
        assert first._interpreter() != second._interpreter()
    finally:
        first.close()
        second.close()


def test_quality_environment_creation_is_thread_safe(tmp_path: Path, monkeypatch) -> None:
    created: list[list[str]] = []

    def execute(args, **kwargs):
        if args[:4] == [_base_python(), "-I", "-m", "venv"]:
            created.append(args)
            time.sleep(0.05)
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, execute)
    quality = QualityMCP(tmp_path)
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
    quality = QualityMCP(tmp_path)

    try:
        quality._interpreter()
        assert calls[0][:5] == [
            _base_python(), "-I", "-m", "venv", "--without-pip",
        ]
        assert "--system-site-packages" not in calls[0]
    finally:
        quality.close()


def test_venv_bootstrap_uses_base_runtime_outside_operator_home(
    tmp_path: Path, monkeypatch
) -> None:
    base_interpreter = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    operator_python = tmp_path / "operator-home" / "venv" / "bin" / "python"
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "executable", str(operator_python))
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: (
            calls.append(args),
            subprocess.CompletedProcess(args, 0, "", ""),
        )[1],
    )
    quality = QualityMCP(tmp_path)

    try:
        quality._interpreter()
    finally:
        quality.close()

    assert calls[0][0] == str(base_interpreter)
    assert calls[0][0] != str(operator_python)


def test_quality_close_removes_environment_and_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    quality = QualityMCP(tmp_path)
    environment = Path(quality._interpreter()).parent.parent

    assert environment.is_dir()
    quality.close()
    quality.close()

    assert not environment.exists()


def test_quality_reports_environment_bootstrap_failure_as_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    def fail(*args, **kwargs):
        raise OSError("cannot create isolated environment")

    _patch_executor(monkeypatch, fail)

    result = QualityMCP(tmp_path).run_build(AgentRole.TESTING)

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
    quality = QualityMCP(tmp_path)

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
    quality = QualityMCP(tmp_path)
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


def test_quality_subprocess_environment_drops_host_injection_and_credentials(
    tmp_path: Path, monkeypatch
) -> None:
    sentinels = {
        "PYTHONPATH": "/untrusted/python",
        "PYTHONHOME": "/untrusted/home",
        "PIP_TARGET": str(tmp_path / "outside"),
        "PIP_PREFIX": str(tmp_path / "prefix"),
        "PIP_USER": "1",
        "OPENAI_API_KEY": "secret-openai",
        "GROQ_API_KEY": "secret-groq",
        "LANGFUSE_SECRET_KEY": "secret-langfuse",
        "GIT_ASKPASS": "steal-credentials",
    }
    for name, value in sentinels.items():
        monkeypatch.setenv(name, value)
    environments: list[dict[str, str]] = []

    def run(args, **kwargs):
        environments.append(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, "", "")

    _patch_executor(monkeypatch, run)
    quality = QualityMCP(tmp_path)

    assert quality.run_build(AgentRole.TESTING).status is ToolStatus.SUCCESS

    try:
        assert environments
        environment = environments[-1]
        assert not sentinels.keys() & environment.keys()
        assert Path(environment["VIRTUAL_ENV"]) == Path(quality._interpreter()).parent.parent
        assert Path(environment["HOME"]).is_relative_to(Path(environment["VIRTUAL_ENV"]))
        assert environment["PIP_CONFIG_FILE"] == os.devnull
        assert not (tmp_path / "outside").exists()
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
    quality = QualityMCP(tmp_path)
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
    quality = QualityMCP(tmp_path, timeout_seconds=0.07)
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
    quality = QualityMCP(tmp_path)

    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS

    try:
        pip_installs = [call for call in calls if "pip" in call and "install" in call]
        assert ["--require-hashes", "--no-build-isolation", "-r", str(lock)] == (
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
    quality = QualityMCP(tmp_path, timeout_seconds=60)

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


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_timeout_terminates_descendant_process_group(tmp_path: Path) -> None:
    escaped = tmp_path / "descendant-escaped"
    quality = QualityMCP(tmp_path, timeout_seconds=10)

    try:
        interpreter = quality._interpreter()
        child = (
            "import signal, time\nfrom pathlib import Path\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(0.8)\n"
            f"Path({str(escaped)!r}).write_text('escaped', encoding='utf-8')\n"
        )
        parent = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-I', '-c', {child!r}])\n"
            "time.sleep(30)\n"
        )
        with pytest.raises(subprocess.TimeoutExpired):
            quality._execute_process(
                [interpreter, "-I", "-c", parent],
                cwd=tmp_path,
                deadline=time.monotonic() + 0.2,
                allow_subprocesses=True,
            )
        time.sleep(0.9)
        assert not escaped.exists()
    finally:
        quality.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_close_terminates_active_process_and_descendants(tmp_path: Path) -> None:
    started = tmp_path / "parent-started"
    escaped = tmp_path / "close-descendant-escaped"
    quality = QualityMCP(tmp_path, timeout_seconds=10)
    interpreter = quality._interpreter()
    environment = Path(interpreter).parent.parent
    child = (
        "import time\nfrom pathlib import Path\n"
        "time.sleep(0.8)\n"
        f"Path({str(escaped)!r}).write_text('escaped', encoding='utf-8')\n"
    )
    parent = (
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-I', '-c', {child!r}], start_new_session=True)\n"
        f"Path({str(started)!r}).write_text('started', encoding='utf-8')\n"
        "time.sleep(30)\n"
    )
    worker = threading.Thread(
        target=lambda: quality._execute_process(
            [interpreter, "-I", "-c", parent],
            cwd=tmp_path,
            deadline=time.monotonic() + 10,
            allow_subprocesses=True,
        )
    )
    worker.start()
    deadline = time.monotonic() + 2
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert started.exists()
    quality.close()
    worker.join(timeout=2)
    time.sleep(0.9)

    assert not worker.is_alive()
    assert not escaped.exists()
    assert not environment.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX escaped-session regression")
def test_escaped_child_holding_pipe_cannot_extend_deadline(tmp_path: Path) -> None:
    child_pid = tmp_path / "setsid-child.pid"
    escaped = tmp_path / "setsid-child-escaped"
    quality = QualityMCP(tmp_path, timeout_seconds=10)

    try:
        interpreter = quality._interpreter()
        child = (
            "import os, time\nfrom pathlib import Path\n"
            f"Path({str(child_pid)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
            "time.sleep(0.7)\n"
            f"Path({str(escaped)!r}).write_text('escaped', encoding='utf-8')\n"
        )
        parent = (
            "import subprocess, sys, time\nfrom pathlib import Path\n"
            f"subprocess.Popen([sys.executable, '-I', '-c', {child!r}], start_new_session=True)\n"
            f"marker = Path({str(child_pid)!r})\n"
            "deadline = time.monotonic() + 1\n"
            "while not marker.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
            "time.sleep(30)\n"
        )
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            quality._execute_process(
                [interpreter, "-I", "-c", parent],
                cwd=tmp_path,
                deadline=time.monotonic() + 0.1,
                allow_subprocesses=True,
            )
        assert time.monotonic() - started < 0.4
        quality.close()
        time.sleep(0.8)
        assert child_pid.exists(), "el PoC no alcanzo a crear el hijo setsid"
        assert not escaped.exists(), "el hijo setsid sobrevivio al timeout y close"
        with pytest.raises(ProcessLookupError):
            os.kill(int(child_pid.read_text(encoding="utf-8")), 0)
    finally:
        quality.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX descendant monitor regression")
def test_late_setsid_child_is_reaped_after_parent_exits_normally(tmp_path: Path) -> None:
    child_pid = tmp_path / "late-child.pid"
    escaped = tmp_path / "late-child-escaped"
    quality = QualityMCP(tmp_path, timeout_seconds=10)
    try:
        interpreter = quality._interpreter()
        child = (
            "import os, time\nfrom pathlib import Path\n"
            f"Path({str(child_pid)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
            "time.sleep(0.6)\n"
            f"Path({str(escaped)!r}).write_text('escaped', encoding='utf-8')\n"
        )
        parent = (
            "import subprocess, sys, time\nfrom pathlib import Path\n"
            "time.sleep(0.1)\n"
            f"subprocess.Popen([sys.executable, '-I', '-c', {child!r}], "
            "start_new_session=True)\n"
            f"marker = Path({str(child_pid)!r})\n"
            "deadline = time.monotonic() + 1\n"
            "while not marker.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
            "time.sleep(0.1)\n"
        )
        completed = quality._execute_process(
            [interpreter, "-I", "-c", parent],
            cwd=tmp_path,
            deadline=time.monotonic() + 3,
            allow_subprocesses=True,
        )
        time.sleep(0.7)

        assert completed.returncode == 0
        assert child_pid.exists()
        assert not escaped.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(int(child_pid.read_text(encoding="utf-8")), 0)
    finally:
        quality.close()


def test_subprocess_output_is_bounded_while_draining(tmp_path: Path) -> None:
    quality = QualityMCP(tmp_path, timeout_seconds=10)

    try:
        interpreter = quality._interpreter()
        completed = quality._execute_process(
            [interpreter, "-I", "-c", "print('x' * 5_000_000)"],
            cwd=tmp_path,
            deadline=time.monotonic() + 5,
        )
        assert completed.returncode == 0
        assert len(completed.stdout.encode()) <= 4096
        assert len(completed.stderr.encode()) <= 4096
    finally:
        quality.close()


def test_mutation_lock_wait_is_inside_operation_deadline(tmp_path: Path, monkeypatch) -> None:
    _patch_executor(
        monkeypatch,
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    quality = QualityMCP(tmp_path, timeout_seconds=0.05)
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
    quality = QualityMCP(tmp_path, timeout_seconds=0.05)
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
    quality = QualityMCP(tmp_path)

    try:
        quality._interpreter()
        assert calls[0][:5] == [
            _base_python(), "-I", "-m", "venv", "--without-pip",
        ]
        assert calls[1][1:4] == ["-I", "-m", "ensurepip"]
    finally:
        quality.close()


def test_windows_termination_uses_recursive_forced_tree_kill(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[list[str], dict]] = []

    class FakeProcess:
        pid = 1234

        def kill(self) -> None:
            raise AssertionError("taskkill succeeded; direct kill must not be used")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "Windows"))
    monkeypatch.setattr(subprocess, "run", run)

    ProcessRunner._terminate_windows_tree(FakeProcess())

    assert calls[0][0][-4:] == ["/PID", "1234", "/T", "/F"]
    assert calls[0][1]["timeout"] == 1


def test_subprocess_path_never_inherits_the_operator_path(tmp_path: Path) -> None:
    """Critico: un backend PEP 517 hostil corre como Python arbitrario durante
    `pip install` y recorre PATH buscando interpretes reales donde plantar un
    sitecustomize.py. Heredar el PATH del operador le entrega esa lista."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0.1.0'\ndependencies=['x']\n", encoding="utf-8"
    )
    quality = QualityMCP(tmp_path, timeout_seconds=10)
    try:
        quality._interpreter(time.monotonic() + 10)
        environment = quality._runner._subprocess_environment()
    finally:
        quality.close()

    entries = environment["PATH"].split(os.pathsep)
    assert entries[0].endswith(_VENV_BIN), "el venv efimero debe ir primero"
    # Aserción positiva: el PATH es exactamente el venv mas un conjunto fijo.
    # Comprobar la ausencia de una ruta concreta pasaba sola segun como se
    # hubiera lanzado la suite.
    expected = _system_path_entries(quality.root, Path(environment["VIRTUAL_ENV"]))
    assert entries[1:] == expected, f"el PATH no es el fijo esperado: {entries[1:]}"
    inherited = [e for e in os.environ.get("PATH", "").split(os.pathsep) if e]
    assert not (set(entries[1:]) & set(inherited) - set(expected))


def test_quality_tools_install_uses_the_complete_declared_lock(tmp_path: Path) -> None:
    """HIGH: --no-deps is safe only with the complete declared toolchain closure."""
    (tmp_path / "requirements.lock").write_text(
        "example==1.0 --hash=sha256:0\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0.1.0'\ndependencies=['example']\n", encoding="utf-8"
    )
    calls: list[list[str]] = []
    quality = QualityMCP(tmp_path, timeout_seconds=10)

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


def test_drain_stream_owns_and_closes_its_descriptor() -> None:
    """El lector debe cerrar su propio stream, sin carreras desde otro hilo."""
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    output = _BoundedOutput()
    reader = threading.Thread(target=ProcessRunner._drain_stream, args=(stream, output))
    reader.start()
    os.write(write_fd, b"owned")
    os.close(write_fd)
    reader.join(timeout=1)

    assert not reader.is_alive()
    assert stream.closed
    assert output.text() == "owned"


def test_missing_workspace_is_reported_without_starting_a_server(tmp_path: Path) -> None:
    """La guarda de workspace inexistente no tenia cobertura."""
    client = MCPQualityClient(tmp_path / "does-not-exist", timeout_seconds=5)
    started = time.monotonic()

    result = client.run_tests(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "MissingWorkspace" in (result.error or "")
    assert time.monotonic() - started < 0.5, "levanto el subproceso antes de rechazar"
    assert client._thread is None


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin sandbox regression")
def test_sandbox_blocks_backend_write_outside_workspace_even_via_base_executable(
    tmp_path: Path,
) -> None:
    """Regression for the reviewer's real PEP 517 escape.

    The child models discovery through ``sys._base_executable`` but points it at
    a controlled host directory outside the project. Before the sandbox this
    creates ``sitecustomize.py`` exactly like the original PoC.
    """
    host_directory = tmp_path.parent / f"quality-host-{tmp_path.name}"
    host_directory.mkdir()
    sentinel = host_directory / "sitecustomize.py"
    quality = QualityMCP(tmp_path, timeout_seconds=10)
    try:
        interpreter = quality._interpreter()
        attack = (
            "import sys\nfrom pathlib import Path\n"
            f"sys._base_executable = {str(host_directory / 'python')!r}\n"
            "target = Path(sys._base_executable).resolve().parent / 'sitecustomize.py'\n"
            "target.write_text('owned', encoding='utf-8')\n"
        )
        completed = quality._execute_process(
            [interpreter, "-I", "-c", attack],
            cwd=tmp_path,
            deadline=time.monotonic() + 5,
        )

        assert completed.returncode != 0
        assert not sentinel.exists(), "el proceso aislado escribio fuera del workspace"
    finally:
        sentinel.unlink(missing_ok=True)
        host_directory.rmdir()
        quality.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin fork policy regression")
def test_offline_sandbox_denies_late_fork(tmp_path: Path) -> None:
    escaped = tmp_path / "late-fork-escaped"
    quality = QualityMCP(tmp_path, timeout_seconds=10)
    try:
        interpreter = quality._interpreter()
        attack = (
            "import os, time\nfrom pathlib import Path\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    time.sleep(0.2)\n"
            f"    Path({str(escaped)!r}).write_text('escaped', encoding='utf-8')\n"
            "    os._exit(0)\n"
            "time.sleep(0.4)\n"
        )
        completed = quality._execute_process(
            [interpreter, "-I", "-c", attack],
            cwd=tmp_path,
            deadline=time.monotonic() + 3,
        )
        time.sleep(0.3)

        assert completed.returncode != 0
        assert not escaped.exists()
    finally:
        quality.close()


def test_sandbox_profile_enables_network_only_for_install_phase(tmp_path: Path) -> None:
    quality = QualityMCP(tmp_path)
    quality._environment = tmp_path / "environment"
    quality._environment.mkdir()

    offline = "\n".join(
        quality._runner._sandbox_command(["python", "-V"], allow_network=False)
    )
    installing = "\n".join(
        quality._runner._sandbox_command(
            ["python", "-m", "pip"],
            allow_network=True,
            allow_subprocesses=True,
        )
    )

    assert "(allow network*)" not in offline
    assert "(allow network*)" in installing
    assert "(deny process-fork)" in offline
    assert "(allow process*)" in installing


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin TLS sandbox regression")
def test_install_phase_can_download_over_real_pypi_tls(tmp_path: Path) -> None:
    quality = QualityMCP(tmp_path, timeout_seconds=30)
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
    quality = QualityMCP(tmp_path)

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


def test_sanitized_path_keeps_legitimate_configured_toolchains(
    tmp_path: Path, monkeypatch
) -> None:
    tool_bin = Path("/usr/bin").resolve()
    monkeypatch.setenv("PATH", os.pathsep.join((str(tool_bin), "relative-bin")))
    quality = QualityMCP(tmp_path)
    quality._environment = tmp_path / "environment"
    quality._environment.mkdir()

    environment = quality._runner._subprocess_environment()
    sandbox = "\n".join(
        quality._runner._sandbox_command(["tool", "--version"], allow_network=False)
    )

    entries = environment["PATH"].split(os.pathsep)
    assert str(tool_bin) in entries
    assert "relative-bin" not in entries
    assert str(tool_bin) in sandbox


def test_system_path_excludes_home_workspace_environment_and_temporary_roots(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "operator-home"
    workspace = tmp_path / "workspace"
    environment = tmp_path / "quality-environment"
    private_tools = home / "private-tools"
    workspace_tools = workspace / "bin"
    environment_tools = environment / "bin"
    for directory in (private_tools, workspace_tools, environment_tools):
        directory.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(
            (
                str(private_tools),
                str(workspace_tools),
                str(environment_tools),
                "/usr/bin",
            )
        ),
    )

    entries = _system_path_entries(workspace, environment)

    assert str(private_tools.resolve()) not in entries
    assert str(workspace_tools.resolve()) not in entries
    assert str(environment_tools.resolve()) not in entries
    assert str(Path("/usr/bin").resolve()) in entries

    quality = QualityMCP(workspace)
    quality._environment = environment
    profile = "\n".join(
        quality._runner._sandbox_command(["python", "-V"], allow_network=False)
    )
    assert str(private_tools.resolve()) not in profile
    assert str(workspace_tools.resolve()) not in profile
    assert str(environment_tools.resolve()) not in profile
    for sensitive_root in (
        "/tmp",
        "/var/tmp",
        "/private/var/tmp",
        "/dev/shm",
        "/run/user",
    ):
        assert f'(require-not (subpath "{sensitive_root}"))' in profile


def test_home_toolchain_path_requires_explicit_valid_opt_in(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "operator-home"
    tool_bin = home / ".local" / "self-contained-tools" / "bin"
    workspace = tmp_path / "workspace"
    environment = tmp_path / "quality-environment"
    for directory in (tool_bin, workspace, environment):
        directory.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ASET_QUALITY_TOOL_PATHS", str(tool_bin))
    monkeypatch.setattr(
        runner_module,
        "_temporary_path_roots",
        lambda: (Path("/not-the-test-temp"),),
        raising=False,
    )

    entries = _system_path_entries(workspace, environment)
    quality = QualityMCP(workspace)
    quality._environment = environment
    profile = "\n".join(
        quality._runner._sandbox_command(["tool", "--version"], allow_network=False)
    )

    assert str(tool_bin.resolve()) in entries
    assert str(tool_bin.resolve()) in profile


@pytest.mark.parametrize("kind", ["relative", "workspace", "temporary"])
def test_home_toolchain_opt_in_rejects_unsafe_paths(
    tmp_path: Path, monkeypatch, kind: str
) -> None:
    home = tmp_path / "operator-home"
    workspace = home / "workspace"
    environment = tmp_path / "quality-environment"
    home.mkdir()
    workspace.mkdir()
    environment.mkdir()
    monkeypatch.setenv("HOME", str(home))
    if kind == "relative":
        configured = "relative/bin"
    elif kind == "workspace":
        configured = str(workspace)
        monkeypatch.setattr(
            runner_module,
            "_temporary_path_roots",
            lambda: (Path("/not-the-test-temp"),),
            raising=False,
        )
    else:
        configured = str(tmp_path)
    monkeypatch.setenv("ASET_QUALITY_TOOL_PATHS", configured)

    with pytest.raises(RuntimeError, match="ASET_QUALITY_TOOL_PATHS"):
        _system_path_entries(workspace, environment)


def test_linux_never_discovers_bubblewrap_from_untrusted_path(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    fake = workspace / "bin" / "bwrap"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(fake.parent))
    monkeypatch.setattr(
        runner_module,
        "_BUBBLEWRAP_CANDIDATES",
        (Path("/path/that/does/not/exist/bwrap"),),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="sandbox is unavailable"):
        ProcessRunner._sandbox_backend()


def test_linux_bubblewrap_candidate_requires_trusted_system_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    fake = tmp_path / "bwrap"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o777)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(
        runner_module,
        "_BUBBLEWRAP_CANDIDATES",
        (fake,),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="sandbox is unavailable"):
        ProcessRunner._sandbox_backend()

    symlink = tmp_path / "bwrap-symlink"
    symlink.symlink_to("/bin/ls")
    monkeypatch.setattr(runner_module, "_BUBBLEWRAP_CANDIDATES", (symlink,))
    with pytest.raises(RuntimeError, match="sandbox is unavailable"):
        ProcessRunner._sandbox_backend()


@pytest.mark.skipif(os.name == "nt", reason="POSIX system metadata regression")
def test_trusted_system_executable_accepts_root_owned_immutable_binary() -> None:
    selected = ProcessRunner._trusted_system_executable((Path("/bin/ls"),))

    assert selected == Path("/bin/ls").resolve(strict=True)


def test_linux_uses_bubblewrap_when_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        ProcessRunner,
        "_trusted_system_executable",
        staticmethod(lambda _candidates: Path("/usr/bin/bwrap")),
    )
    quality = QualityMCP(tmp_path)
    quality._environment = tmp_path / "environment"
    quality._environment.mkdir()

    command = quality._runner._sandbox_command(["python", "-V"], allow_network=False)

    assert command[0] == "/usr/bin/bwrap"
    assert "--unshare-all" in command
    assert "--share-net" not in command
    assert ["--bind", str(tmp_path.resolve()), str(tmp_path.resolve())] == command[
        command.index("--bind") : command.index("--bind") + 3
    ]
    assert ["--tmpfs", "/tmp"] == command[
        command.index("--tmpfs") : command.index("--tmpfs") + 2
    ]
    assert "/home" in command

    mount_sources = [
        command[index + 1]
        for index, argument in enumerate(command[:-2])
        if argument in {"--bind", "--ro-bind"}
    ]
    assert "/" not in mount_sources, "bubblewrap must never expose the host root"
    assert str(Path.home().resolve()) not in mount_sources, (
        "bubblewrap must never expose the operator home"
    )

    installing = quality._runner._sandbox_command(["python", "-m", "pip"], allow_network=True)
    assert "--share-net" in installing


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux regression")
def test_real_linux_bubblewrap_blocks_host_write(tmp_path: Path) -> None:
    try:
        ProcessRunner._sandbox_backend()
    except RuntimeError:
        pytest.skip("trusted system bubblewrap is unavailable")
    host_directory = tmp_path.parent / f"quality-linux-host-{tmp_path.name}"
    host_directory.mkdir()
    sentinel = host_directory / "escaped"
    quality = QualityMCP(tmp_path, timeout_seconds=10)
    try:
        interpreter = quality._interpreter()
        safe = quality._execute_process(
            [interpreter, "-I", "-c", "print('sandbox-ready')"],
            cwd=tmp_path,
            deadline=time.monotonic() + 5,
        )
        attack = quality._execute_process(
            [
                interpreter,
                "-I",
                "-c",
                (
                    "from pathlib import Path; "
                    f"Path({str(sentinel)!r}).write_text('owned', encoding='utf-8')"
                ),
            ],
            cwd=tmp_path,
            deadline=time.monotonic() + 5,
        )

        assert safe.returncode == 0, safe.stderr
        assert attack.returncode != 0
        assert not sentinel.exists()
    finally:
        sentinel.unlink(missing_ok=True)
        host_directory.rmdir()
        quality.close()


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
    quality = QualityMCP(tmp_path)
    try:
        assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS
    finally:
        quality.close()

    assert calls
    for command, network in calls:
        is_install = "pip" in command and "install" in command
        assert network is is_install, (command, network)


@pytest.mark.skipif(os.name == "nt", reason="POSIX cancellable-pipe regression")
def test_output_reader_is_cancelable_when_escaped_child_holds_pipe() -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    output = _BoundedOutput()
    stop = threading.Event()
    reader = threading.Thread(
        target=ProcessRunner._drain_stream,
        args=(stream, output, stop),
    )
    reader.start()

    stop.set()
    reader.join(timeout=0.5)
    os.close(write_fd)

    assert not reader.is_alive()
    assert stream.closed


def test_startup_scavenges_only_dead_owned_quality_environments(
    tmp_path: Path, monkeypatch
) -> None:
    base = tmp_path / "quality-environments"
    monkeypatch.setattr(ProcessRunner, "_environment_root", staticmethod(lambda: base))
    dead = base / "env-dead"
    foreign = base / "env-foreign"
    dead.mkdir(parents=True)
    foreign.mkdir()
    (dead / ".aset-quality-owner").write_text(
        (
            '{"schema":"aset-quality-v1","uid":'
            f"{os.getuid() if hasattr(os, 'getuid') else 0},"
            '"pid":99999999}'
        ),
        encoding="utf-8",
    )
    (foreign / ".aset-quality-owner").write_text("not-our-marker", encoding="utf-8")

    ProcessRunner(tmp_path)._scavenge_environments()

    assert not dead.exists()
    assert foreign.exists(), "el scavenger borro un directorio sin marcador valido"


def test_unsupported_platform_fails_closed_without_starting_a_process(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module,
        "_BUBBLEWRAP_CANDIDATES",
        (Path("/path/that/does/not/exist/bwrap"),),
    )
    quality = QualityMCP(tmp_path)

    result = quality.run_build(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "sandbox is unavailable" in (result.error or "")
    assert quality._environment is None


def test_windows_quality_backend_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    quality = QualityMCP(tmp_path)

    result = quality.run_build(AgentRole.TESTING)

    assert result.status is ToolStatus.UNAVAILABLE
    assert "sandbox is unavailable" in (result.error or "")
    assert quality._environment is None


def test_quality_platform_and_home_toolchain_contract_is_documented() -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")

    assert "QualityMCP" in readme
    assert "Darwin" in readme
    assert "Linux + Bubblewrap" in readme
    assert "Windows" in readme and "UNAVAILABLE" in readme
    assert "ASET_QUALITY_TOOL_PATHS" in readme


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

    quality = QualityMCP(project, timeout_seconds=180)
    try:
        linted = quality.run_linter(AgentRole.DEVELOPER)
        scanned = quality.run_security_scan(AgentRole.SECURITY)
    finally:
        quality.close()

    for result in (linted, scanned):
        combined = (result.output_summary or "") + (result.error or "")
        assert "Failed to read" not in combined, combined[:200]
        assert result.status is not ToolStatus.UNAVAILABLE
