"""Run file-heavy toolchains on a native volume while host tools own sources.

Docker Desktop bind mounts are unsuitable for npm's concurrent renames and
directory creation on some hosts. Only transfer containers cross the filesystem
boundary, using tar over pipes; the actual command sees the entire repository
on a native volume. Sources, reports and build output return as checked deltas.
Dependency trees stay inside the volume until this runner closes.
"""

from __future__ import annotations

import io
import os
import posixpath
import stat
import subprocess
import tarfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from engineering_team.mcp.command import CommandRequest
from engineering_team.mcp.container import WORKSPACE_MOUNT, ContainerRunner

_TRANSFER_LIMIT = 256 * 1024 * 1024


class WorkspaceSyncError(RuntimeError):
    """The source boundary cannot be synchronized without losing evidence."""


@dataclass(frozen=True)
class _Entry:
    kind: str
    mode: int
    data: bytes = b""
    target: str = ""


def _path(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise WorkspaceSyncError("workspace archive contains an unsafe path")
    return str(path)


def _private(name: str) -> bool:
    # Dependency trees stay in the volume. Repository metadata stays on the host:
    # commands see it through a read-only bind, and nothing they write to it may
    # reach the checkout that delivery later runs git in.
    parts = PurePosixPath(name).parts
    return "node_modules" in parts or parts[:1] == (".git",)


def _check_link(name: str, target: str) -> None:
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    if (
        not target or target.startswith("/") or resolved == ".."
        or resolved.startswith("../") or "\x00" in target
    ):
        raise WorkspaceSyncError("workspace symlink leaves the repository")


def _validate(entries: dict[str, _Entry]) -> None:
    for name, entry in entries.items():
        _path(name)
        if entry.kind == "link":
            _check_link(name, entry.target)
        for parent in PurePosixPath(name).parents:
            if str(parent) == ".":
                continue
            if str(parent) in entries and entries[str(parent)].kind != "dir":
                raise WorkspaceSyncError("workspace entry has a non-directory ancestor")


def _snapshot(root: Path) -> dict[str, _Entry]:
    entries: dict[str, _Entry] = {}
    total = 0

    def visit(fd: int, prefix: str = "") -> None:
        nonlocal total
        for item in sorted(os.scandir(fd), key=lambda entry: entry.name):
            name = f"{prefix}/{item.name}" if prefix else item.name
            if _private(name):
                continue
            info = os.stat(item.name, dir_fd=fd, follow_symlinks=False)
            mode = stat.S_IMODE(info.st_mode) & 0o777
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(item.name, dir_fd=fd)
                _check_link(name, target)
                entries[name] = _Entry("link", mode, target=target)
            elif stat.S_ISDIR(info.st_mode):
                entries[name] = _Entry("dir", mode)
                child = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    visit(child, name)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > _TRANSFER_LIMIT:
                    raise WorkspaceSyncError("workspace transfer exceeds the size limit")
                opened = os.open(item.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(opened, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise WorkspaceSyncError("workspace file changed type during transfer")
                    data = stream.read(_TRANSFER_LIMIT - total + info.st_size + 1)
                if len(data) != info.st_size:
                    raise WorkspaceSyncError("workspace file changed during transfer")
                entries[name] = _Entry("file", mode, data)
            else:
                raise WorkspaceSyncError("workspace contains an unsupported special file")

    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(fd)
    finally:
        os.close(fd)
    _validate(entries)
    return entries


def _archive(entries: dict[str, _Entry]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, entry in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.mode = entry.mode
            if entry.kind == "dir":
                info.type = tarfile.DIRTYPE
            elif entry.kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = entry.target
            else:
                info.size = len(entry.data)
            archive.addfile(info, io.BytesIO(entry.data) if entry.kind == "file" else None)
    result = buffer.getvalue()
    if len(result) > _TRANSFER_LIMIT:
        raise WorkspaceSyncError("workspace transfer exceeds the size limit")
    return result


def _read_archive(data: bytes) -> dict[str, _Entry]:
    if len(data) > _TRANSFER_LIMIT:
        raise WorkspaceSyncError("workspace transfer exceeds the size limit")
    entries: dict[str, _Entry] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                if member.name in (".", "./"):
                    continue
                name = _path(member.name)
                if _private(name):
                    continue
                if name in entries:
                    raise WorkspaceSyncError("workspace archive repeats a path")
                mode = member.mode & 0o777
                if member.isdir():
                    entry = _Entry("dir", mode)
                elif member.issym():
                    _check_link(name, member.linkname)
                    entry = _Entry("link", mode, target=member.linkname)
                elif member.isfile():
                    total += member.size
                    if total > _TRANSFER_LIMIT:
                        raise WorkspaceSyncError("workspace transfer exceeds the size limit")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise WorkspaceSyncError("workspace archive has missing file data")
                    entry = _Entry("file", mode, stream.read())
                    if len(entry.data) != member.size:
                        raise WorkspaceSyncError("workspace archive has truncated file data")
                else:
                    raise WorkspaceSyncError("workspace archive contains a special file or hard link")
                entries[name] = entry
    except (tarfile.TarError, OSError, ValueError):
        raise WorkspaceSyncError("workspace archive could not be read") from None
    _validate(entries)
    return entries


@contextmanager
def _parent_fd(root: Path, name: str):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in PurePosixPath(name).parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, PurePosixPath(name).name
    finally:
        os.close(fd)


def _apply_host_delta(root: Path, before: dict[str, _Entry], after: dict[str, _Entry]) -> None:
    _validate(after)
    current = _snapshot(root)
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    for name in changed:
        if current.get(name) not in (before.get(name), after.get(name)):
            raise WorkspaceSyncError("workspace synchronization conflict with a host edit")
        for parent in PurePosixPath(name).parents:
            key = str(parent)
            if key != "." and key in current and current[key].kind != "dir":
                raise WorkspaceSyncError("workspace synchronization conflict with a host parent")
    # Remove replaced objects and children first. rmdir deliberately refuses to
    # destroy a dependency tree or a concurrent file absent from our snapshot.
    remove = [name for name in changed if name in current and (
        name not in after or current[name].kind != after[name].kind
        or current[name].kind == "link"
    )]
    try:
        for name in sorted(remove, key=lambda path: (path.count("/"), path), reverse=True):
            with _parent_fd(root, name) as (fd, leaf):
                if current[name].kind == "dir":
                    os.rmdir(leaf, dir_fd=fd)
                else:
                    os.unlink(leaf, dir_fd=fd)
        for name in sorted(changed & after.keys(), key=lambda path: (path.count("/"), path)):
            entry = after[name]
            with _parent_fd(root, name) as (fd, leaf):
                if entry.kind == "dir":
                    if name not in current or current[name].kind != "dir":
                        os.mkdir(leaf, entry.mode | 0o700, dir_fd=fd)
                    os.chmod(leaf, entry.mode | 0o700, dir_fd=fd, follow_symlinks=False)
                elif entry.kind == "link":
                    os.symlink(entry.target, leaf, dir_fd=fd)
                else:
                    temporary = f".aset-transfer-{uuid.uuid4().hex}"
                    opened = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     entry.mode, dir_fd=fd)
                    try:
                        with os.fdopen(opened, "wb") as stream:
                            stream.write(entry.data)
                            os.fchmod(stream.fileno(), entry.mode)
                        os.replace(temporary, leaf, src_dir_fd=fd, dst_dir_fd=fd)
                    finally:
                        try:
                            os.unlink(temporary, dir_fd=fd)
                        except FileNotFoundError:
                            pass
        for name in sorted(changed & after.keys(), key=lambda path: path.count("/"), reverse=True):
            if after[name].kind == "dir":
                with _parent_fd(root, name) as (fd, leaf):
                    os.chmod(leaf, after[name].mode, dir_fd=fd, follow_symlinks=False)
    except OSError:
        raise WorkspaceSyncError("workspace synchronization could not safely update the host") from None


class NativeWorkspaceRunner(ContainerRunner):
    """ContainerRunner with a native repository volume and checked host deltas."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = Path(self.workspace).resolve()
        self._workspace_volume = f"aset-workspace-{self._token}"
        self._workspace_created = False
        self._published: dict[str, _Entry] = {}
        self._sync_lock = threading.Lock()
        self._sync_failed = False

    def _container_command(self, name: str, request: CommandRequest) -> list[str]:
        args = super()._container_command(name, request)
        bind = f"type=bind,source={self.workspace},target={WORKSPACE_MOUNT}"
        args[args.index(bind)] = f"type=volume,source={self._workspace_volume},target={WORKSPACE_MOUNT}"
        return args

    def _transfer(self, command: list[str], deadline: float, data: bytes | None = None,
                  *, root: bool = False) -> bytes:
        name = self._reserve_name()
        args = [self.runtime, "run", "--rm", "--interactive", "--name", name,
                *self._labels, "--network", "none", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--memory", self.limits.memory,
                "--pids-limit", str(self.limits.pids), "--cpus", self.limits.cpus,
                "--mount", f"type=volume,source={self._workspace_volume},target={WORKSPACE_MOUNT}"]
        if root:
            args += ["--user", "0:0", "--cap-add", "CHOWN"]
        elif hasattr(os, "getuid"):
            args += ["--user", f"{os.getuid()}:{os.getgid()}"]
        args += [self.image, *command]
        try:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise WorkspaceSyncError("workspace transfer deadline expired")
            output = self._transfer_output(args, data, timeout)
            return output
        except (OSError, subprocess.SubprocessError):
            raise WorkspaceSyncError("workspace transfer container was interrupted") from None
        finally:
            self._quiet([self.runtime, "rm", "--force", name], timeout=10)
            with self._lock:
                self._live_containers.discard(name)

    @staticmethod
    def _transfer_output(args: list[str], data: bytes | None, timeout: float) -> bytes:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        output = bytearray()
        overflow = threading.Event()
        incomplete = threading.Event()

        def feed():
            try:
                if data:
                    process.stdin.write(data)
                process.stdin.close()
            except (OSError, ValueError):
                incomplete.set()

        def drain(stream, capture):
            try:
                while chunk := stream.read(65536):
                    if capture:
                        if len(output) + len(chunk) > _TRANSFER_LIMIT:
                            overflow.set()
                            process.kill()
                            break
                        output.extend(chunk)
            except (OSError, ValueError):
                incomplete.set()
            finally:
                stream.close()

        threads = [threading.Thread(target=feed, daemon=True),
                   threading.Thread(target=drain, args=(process.stdout, True), daemon=True),
                   threading.Thread(target=drain, args=(process.stderr, False), daemon=True)]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=timeout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for thread in threads:
                thread.join(timeout=2)
        if overflow.is_set():
            raise WorkspaceSyncError("workspace transfer exceeds the size limit")
        if incomplete.is_set() or any(thread.is_alive() for thread in threads):
            raise WorkspaceSyncError("workspace transfer was incomplete")
        if process.returncode:
            raise WorkspaceSyncError("workspace transfer container failed")
        return bytes(output)

    def _ensure_workspace(self, deadline: float) -> None:
        if self._workspace_created:
            return
        created = self._quiet([self.runtime, "volume", "create", *self._labels, self._workspace_volume],
                              timeout=max(0.1, min(60, deadline - time.monotonic())))
        if created is None or created.returncode:
            raise WorkspaceSyncError("native workspace volume was not created")
        self._workspace_created = True
        if hasattr(os, "getuid"):
            self._transfer(["chown", f"{os.getuid()}:{os.getgid()}", str(WORKSPACE_MOUNT)], deadline, root=True)

    def _push(self, snapshot: dict[str, _Entry], deadline: float) -> None:
        removed = [name for name in self._published if name not in snapshot or (
            self._published[name].kind != snapshot[name].kind
            or self._published[name].kind == "link" and self._published[name] != snapshot[name]
        )]
        # Argument values never become shell code. Full paths cannot be options.
        for offset in range(0, len(removed), 100):
            paths = [str(WORKSPACE_MOUNT / name) for name in removed[offset:offset + 100]]
            self._transfer(["rm", "-rf", "--", *paths], deadline)
        changed = {name: entry for name, entry in snapshot.items() if self._published.get(name) != entry}
        if changed:
            self._transfer(["tar", "--no-same-owner", "-xpf", "-", "-C", str(WORKSPACE_MOUNT)],
                           deadline, _archive(changed))

    def _pull(self, deadline: float) -> dict[str, _Entry]:
        command = ["tar", "--hard-dereference", "--exclude=./node_modules",
                   "--exclude=*/node_modules", "--exclude=./.git",
                   "-cf", "-", "-C", str(WORKSPACE_MOUNT), "."]
        return _read_archive(self._transfer(command, deadline))

    def execute(self, request: CommandRequest) -> subprocess.CompletedProcess[str]:
        with self._sync_lock:
            if self.closing or self._sync_failed:
                raise WorkspaceSyncError("native workspace is closed or synchronization failed")
            try:
                self._ensure_workspace(request.deadline)
                before = _snapshot(self.workspace)
                self._push(before, request.deadline)
                try:
                    return super().execute(request)
                finally:
                    # Even a failing command can create useful reports. Give
                    # bounded cleanup time after a command consumed its budget.
                    # Closing cancels the boundary; do not start a new transfer
                    # container after close has already killed existing work.
                    if not self.closing:
                        after = self._pull(max(request.deadline, time.monotonic() + 30))
                        _apply_host_delta(self.workspace, before, after)
                        self._published = after
            except Exception:
                self._sync_failed = True
                raise

    def close(self) -> None:
        super().close()
        with self._sync_lock:
            if self._workspace_created:
                self._quiet([self.runtime, "volume", "rm", "--force", self._workspace_volume], timeout=30)
                self._workspace_created = False
