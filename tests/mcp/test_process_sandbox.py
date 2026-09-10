"""Everything that is true only of the process sandbox.

`ProcessRunner` runs commands under an OS sandbox on the host kernel:
`sandbox-exec` on Darwin, Bubblewrap on Linux, and a refusal anywhere else.
Its tests -- which profile it writes, which PATH it rebuilds, which binary it
will accept as bwrap, how it kills a tree on Windows -- describe that boundary
and nothing above it.

They live in one file so that retiring the backend is one deletion rather than
a hunt through the quality-layer suite, and so that until then it is obvious
which coverage belongs to a boundary that exists on one of the three platforms
this system runs on. The quality-layer properties they used to sit beside stay
in `test_quality.py`, where they are asserted against whichever runner the
gate actually uses.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import engineering_team.mcp.runner as runner_module
from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.command import CommandRequest, CommandRunner
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.runner import (
    _VENV_BIN,
    ProcessRunner,
    _BoundedOutput,
    _system_path_entries,
)


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


def test_process_runner_stands_alone_without_quality() -> None:
    """The sandbox no longer needs a QualityMCP to exist."""
    runner = ProcessRunner(Path.cwd())
    assert isinstance(runner, CommandRunner)
    assert runner.environment is None
    assert runner.closing is False
    runner.close()
    assert runner.closing is True


@pytest.mark.skipif(
    sys.platform not in ("darwin", "linux"), reason="sandbox backend is host-specific"
)
def test_process_runner_still_runs_a_real_command(tmp_path: Path) -> None:
    """The extraction kept a working runner, not just the shape of one."""
    runner = ProcessRunner(tmp_path)
    runner.environment = tmp_path
    completed = runner.execute(
        CommandRequest(
            args=("/bin/echo", "bounded"),
            cwd=tmp_path,
            deadline=time.monotonic() + 30,
        )
    )
    assert completed.returncode == 0
    assert "bounded" in completed.stdout
    runner.close()


@pytest.mark.skipif(
    sys.platform not in ("darwin", "linux"), reason="sandbox backend is host-specific"
)
def test_process_runner_still_denies_reads_outside_its_roots(tmp_path: Path) -> None:
    """The boundary survived the move.

    `sys.executable` is the operator's own virtual environment, outside the
    workspace and the ephemeral environment the runner grants. Launching it must
    fail on its own configuration file rather than start an interpreter that can
    see the operator's site-packages.
    """
    runner = ProcessRunner(tmp_path)
    runner.environment = tmp_path
    completed = runner.execute(
        CommandRequest(
            args=(sys.executable, "-c", "print('escaped')"),
            cwd=tmp_path,
            deadline=time.monotonic() + 30,
        )
    )
    assert completed.returncode != 0
    assert "escaped" not in completed.stdout
    assert "not permitted" in completed.stderr.lower()
    runner.close()


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


def test_quality_instances_have_distinct_environments(tmp_path: Path) -> None:
    first = QualityMCP(tmp_path)
    second = QualityMCP(tmp_path)

    try:
        assert first._interpreter() != second._interpreter()
    finally:
        first.close()
        second.close()


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
