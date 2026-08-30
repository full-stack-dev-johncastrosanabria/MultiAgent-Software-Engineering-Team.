import importlib.metadata
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.mcp.quality import QualityMCP


def _patch_executor(monkeypatch, callback) -> None:
    def execute(quality, args, *, cwd, deadline):
        return callback(
            args,
            cwd=cwd,
            deadline=deadline,
            env=quality._subprocess_environment(),
            timeout=quality._remaining(deadline),
        )

    monkeypatch.setattr(QualityMCP, "_execute_process", execute)


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
    assert calls[0][:5] == [sys.executable, "-I", "-m", "venv", "--without-pip"]
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
            f"pytest=={importlib.metadata.version('pytest')}",
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
        if args[:4] == [sys.executable, "-I", "-m", "venv"]:
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
            sys.executable, "-I", "-m", "venv", "--without-pip",
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
        f"subprocess.Popen([sys.executable, '-I', '-c', {child!r}])\n"
        f"Path({str(started)!r}).write_text('started', encoding='utf-8')\n"
        "time.sleep(30)\n"
    )
    worker = threading.Thread(
        target=lambda: quality._execute_process(
            [interpreter, "-I", "-c", parent],
            cwd=tmp_path,
            deadline=time.monotonic() + 10,
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
    quality = QualityMCP(tmp_path, timeout_seconds=10)

    try:
        interpreter = quality._interpreter()
        child = "import time; time.sleep(0.7)"
        parent = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-I', '-c', {child!r}], start_new_session=True)\n"
            "time.sleep(30)\n"
        )
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            quality._execute_process(
                [interpreter, "-I", "-c", parent],
                cwd=tmp_path,
                deadline=time.monotonic() + 0.1,
            )
        assert time.monotonic() - started < 0.4
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
        assert calls[0][:5] == [sys.executable, "-I", "-m", "venv", "--without-pip"]
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

    QualityMCP._terminate_windows_tree(FakeProcess())

    assert calls[0][0][-4:] == ["/PID", "1234", "/T", "/F"]
    assert calls[0][1]["timeout"] == 1
