"""Small synchronous boundary over official asynchronous MCP stdio sessions."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, TypeVar

from mcp import Client, StdioServerParameters

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult

# TypeVar y no `typing.Self`: Self es 3.11+ y el proyecto declara
# requires-python = ">=3.10". `test_client_source_is_importable_on_python_310`
# lo fija, asi que el autofix de PYI019 romperia esa compatibilidad.
_ClientT = TypeVar("_ClientT", bound="_MCPStdioClient")


class _MCPStdioClient:
    transport = "stdio"

    def __init__(self, root: str | Path, kind: str, *, timeout_seconds: float = 60) -> None:
        self.root = Path(root).resolve()
        self.kind = kind
        self.timeout_seconds = timeout_seconds
        self.last_protocol_version: str | None = None
        self.last_server_name: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session_task: asyncio.Task | None = None
        self._requests: asyncio.Queue | None = None
        self._ready = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._worker_failed = False
        self.abandoned_worker = False

    def _parameters(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=sys.executable,
            args=[
                "-I", "-m", "engineering_team.mcp.server", "--kind", self.kind,
                "--root", str(self.root), "--timeout", str(self.timeout_seconds),
            ],
            cwd=Path(sys.executable).resolve().parent,
        )

    def _deadline(self) -> float:
        return time.monotonic() + float(self.timeout_seconds)

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("MCP request deadline exceeded")
        return remaining

    def start(self: _ClientT, *, deadline: float | None = None) -> _ClientT:  # noqa: PYI019
        """Start one background event loop and one persistent stdio session."""
        deadline = self._deadline() if deadline is None else deadline
        with self._lifecycle_lock:
            if self._thread is None:
                self._worker_failed = False
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._run_loop,
                    name=f"mcp-{self.kind}-stdio",
                    daemon=True,
                )
                self._thread.start()
        if not self._ready.wait(timeout=self._remaining(deadline)):
            raise TimeoutError("MCP client event loop did not start")
        if self._worker_failed:
            raise RuntimeError("MCP session is unavailable")
        self._request("connect", deadline=deadline)
        return self

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._requests = asyncio.Queue()
        self._session_task = self._loop.create_task(self._session_worker())
        self._ready.set()
        try:
            self._loop.run_until_complete(self._session_task)
        except asyncio.CancelledError:
            pass
        finally:
            pending = [
                task for task in asyncio.all_tasks(self._loop) if not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def _submit(self, operation, *, deadline: float):
        loop = self._loop
        if loop is None or self._thread is None:
            raise RuntimeError("MCP client has not started")
        future = asyncio.run_coroutine_threadsafe(operation, loop)
        return future.result(timeout=self._remaining(deadline))

    async def _enqueue(self, action: str, *arguments: Any) -> Any:
        if self._requests is None:
            raise RuntimeError("MCP request queue is unavailable")
        response = asyncio.get_running_loop().create_future()
        await self._requests.put((action, arguments, response))
        return await response

    def _request(
        self, action: str, *arguments: Any, deadline: float | None = None
    ) -> Any:
        deadline = self._deadline() if deadline is None else deadline
        return self._submit(self._enqueue(action, *arguments), deadline=deadline)

    async def _session_worker(self) -> None:
        current_response: asyncio.Future | None = None
        close_response: asyncio.Future | None = None
        try:
            async with Client(
                self._parameters(), read_timeout_seconds=float(self.timeout_seconds)
            ) as session:
                self._capture_session(session)
                while True:
                    assert self._requests is not None
                    action, arguments, current_response = await self._requests.get()
                    if action == "close":
                        close_response = current_response
                        current_response = None
                        break
                    try:
                        if action == "connect":
                            value: Any = None
                        elif action == "list_tools":
                            result = await session.list_tools()
                            value = [tool.name for tool in result.tools]
                        elif action == "call_tool":
                            value = await session.call_tool(arguments[0], arguments[1])
                        else:
                            raise ValueError(f"unknown MCP client action: {action}")
                        current_response.set_result(value)
                    except Exception as exc:  # noqa: BLE001 - isolate protocol failures
                        if not current_response.done():
                            current_response.set_exception(exc)
                    current_response = None
        except Exception as exc:  # noqa: BLE001 - surface server/session failures
            self._worker_failed = True
            if current_response is not None and not current_response.done():
                current_response.set_exception(exc)
            if self._requests is not None:
                while not self._requests.empty():
                    _, _, response = self._requests.get_nowait()
                    if not response.done():
                        response.set_exception(exc)
        finally:
            if close_response is not None and not close_response.done():
                close_response.set_result(None)

    @staticmethod
    def _decode_result(result: Any) -> ToolResult:
        payload = result.structured_content
        if not isinstance(payload, dict):
            text = next(
                (item.text for item in result.content if hasattr(item, "text")), "{}"
            )
            payload = json.loads(text)
        return ToolResult.model_validate(payload)

    def _capture_session(self, session: Client) -> None:
        self.last_protocol_version = str(session.protocol_version)
        if session.server_info is not None:
            self.last_server_name = session.server_info.name

    def list_tools(self) -> list[str]:
        deadline = self._deadline()
        self.start(deadline=deadline)
        return self._request("list_tools", deadline=deadline)

    def _unavailable(self, name: str, role: AgentRole, reason: str) -> ToolResult:
        return ToolResult(
            tool_name=name,
            allowed_role=role,
            status=ToolStatus.UNAVAILABLE,
            input_summary="safe",
            output_summary="",
            duration_ms=0,
            evidence_reference=f"mcp://{self.kind}/{name}",
            error=f"MCP_ERROR: {reason}",
        )

    def call_tool(self, name: str, role: AgentRole, **arguments: Any) -> ToolResult:
        if not self.root.is_dir():
            # Antes esto salia solo: el subproceso se lanzaba con cwd=self.root y
            # fallaba al no existir. Aislar el cwd del proyecto -necesario para
            # que modulos locales no sombreen el toolchain- desacoplo ese efecto,
            # asi que la condicion se comprueba en vez de deducirse.
            return self._unavailable(name, role, "MissingWorkspace")
        deadline = self._deadline()
        try:
            self.start(deadline=deadline)
            result = self._request(
                "call_tool",
                name,
                {"role": role.value, **arguments},
                deadline=deadline,
            )
            return self._decode_result(result)
        except Exception as exc:  # noqa: BLE001 - normalize the MCP boundary
            return ToolResult(
                tool_name=name,
                allowed_role=role,
                status=ToolStatus.UNAVAILABLE,
                input_summary="safe",
                output_summary="",
                duration_ms=0,
                evidence_reference=f"mcp://{self.kind}/{name}",
                error=f"MCP_ERROR: {type(exc).__name__}",
            )

    def close(self) -> None:
        request_deadline = self._deadline()
        cleanup_deadline = time.monotonic() + max(float(self.timeout_seconds), 2.0)
        with self._lifecycle_lock:
            loop = self._loop
            thread = self._thread
            if loop is None or thread is None:
                return
            try:
                if thread.is_alive() and not self._worker_failed:
                    try:
                        self._request("close", deadline=request_deadline)
                    except Exception:  # noqa: BLE001 - teardown still must stop the loop
                        self._worker_failed = True
            finally:
                if thread.is_alive():
                    task = self._session_task
                    if task is not None and not task.done():
                        loop.call_soon_threadsafe(task.cancel)
                thread.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
                if thread.is_alive():
                    # Se registra y no se lanza: close() corre en `finally` y en
                    # `__exit__`, donde lanzar reemplaza la excepcion real que el
                    # llamador venia manejando -y ademas no detiene nada-. El hilo
                    # es daemon, asi que no impide salir del proceso.
                    self._worker_failed = True
                    self.abandoned_worker = True
                else:
                    self.abandoned_worker = False
                    self._loop = None
                    self._thread = None
                    self._session_task = None
                    self._requests = None
                    self._ready.clear()

    def __enter__(self: _ClientT) -> _ClientT:  # noqa: PYI019
        return self.start()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class MCPRepositoryClient(_MCPStdioClient):
    def __init__(self, root: str | Path, *, timeout_seconds: float = 60) -> None:
        super().__init__(root, "repository", timeout_seconds=timeout_seconds)

    def list_files(self, role: AgentRole) -> ToolResult:
        return self.call_tool("list_files", role)

    def read_file(self, role: AgentRole, relative: str) -> ToolResult:
        return self.call_tool("read_file", role, relative=relative)

    def search_code(self, role: AgentRole, query: str) -> ToolResult:
        return self.call_tool("search_code", role, query=query)

    def get_file_content(self, role: AgentRole, relative: str) -> ToolResult:
        return self.call_tool("get_file_content", role, relative=relative)

    def create_file(self, role: AgentRole, relative: str, content: str) -> ToolResult:
        return self.call_tool("create_file", role, relative=relative, content=content)

    def update_file(self, role: AgentRole, relative: str, content: str) -> ToolResult:
        return self.call_tool("update_file", role, relative=relative, content=content)

    def get_diff(self, role: AgentRole) -> ToolResult:
        return self.call_tool("get_diff", role)


class MCPQualityClient(_MCPStdioClient):
    def __init__(self, root: str | Path, *, timeout_seconds: float = 60) -> None:
        super().__init__(root, "quality", timeout_seconds=timeout_seconds)

    def run_tests(self, role: AgentRole, paths: list[str] | None = None) -> ToolResult:
        return self.call_tool("run_tests", role, paths=paths)

    def get_test_results(self, role: AgentRole) -> ToolResult:
        return self.call_tool("get_test_results", role)

    def run_build(self, role: AgentRole) -> ToolResult:
        return self.call_tool("run_build", role)

    def get_build_status(self, role: AgentRole) -> ToolResult:
        return self.call_tool("get_build_status", role)

    def run_linter(self, role: AgentRole) -> ToolResult:
        return self.call_tool("run_linter", role)

    def scan_dependencies(self, role: AgentRole) -> ToolResult:
        return self.call_tool("scan_dependencies", role)

    def run_security_scan(self, role: AgentRole) -> ToolResult:
        return self.call_tool("run_security_scan", role)

    def get_security_report(self, role: AgentRole) -> ToolResult:
        return self.call_tool("get_security_report", role)
