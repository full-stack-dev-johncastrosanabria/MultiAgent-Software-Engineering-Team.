"""Official MCP SDK server bootstrap for bounded repository and quality tools."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.contracts.models import ToolResult
from engineering_team.mcp.quality import QualityMCP
from engineering_team.mcp.repository import RepositoryMCP


def _wire_result(server_name: str, operation: Callable[..., ToolResult], *args: Any) -> dict[str, Any]:
    result = operation(*args).model_copy(
        update={"evidence_reference": f"mcp://{server_name}/{operation.__name__}"}
    )
    return result.model_dump(mode="json")


def build_repository_server(root: str | Path) -> MCPServer:
    backend = RepositoryMCP(root)
    server = MCPServer(name="engineering-team-repository", log_level="ERROR")

    @server.tool()
    def list_files(role: str) -> dict[str, Any]:
        return _wire_result("repository", backend.list_files, AgentRole(role))

    @server.tool()
    def read_file(role: str, relative: str) -> dict[str, Any]:
        result = backend.read_file(AgentRole(role), relative).model_copy(update={
            "input_summary": f"path={relative}",
            "evidence_reference": "mcp://repository/read_file",
        })
        return result.model_dump(mode="json")

    @server.tool()
    def search_code(role: str, query: str) -> dict[str, Any]:
        result = backend.search_code(AgentRole(role), query).model_copy(update={
            "input_summary": "query=bounded",
            "evidence_reference": "mcp://repository/search_code",
        })
        return result.model_dump(mode="json")

    @server.tool()
    def get_file_content(role: str, relative: str) -> dict[str, Any]:
        result = backend.get_file_content(AgentRole(role), relative).model_copy(
            update={
                "input_summary": f"path={relative}",
                "evidence_reference": "mcp://repository/get_file_content",
            }
        )
        return result.model_dump(mode="json")

    @server.tool()
    def create_file(role: str, relative: str, content: str) -> dict[str, Any]:
        return _wire_result(
            "repository", backend.create_file, AgentRole(role), relative, content
        )

    @server.tool()
    def update_file(role: str, relative: str, content: str) -> dict[str, Any]:
        return _wire_result(
            "repository", backend.update_file, AgentRole(role), relative, content
        )

    @server.tool()
    def get_diff(role: str) -> dict[str, Any]:
        return _wire_result("repository", backend.get_diff, AgentRole(role))

    return server


def build_quality_server(
    root: str | Path,
    timeout_seconds: float = 60,
    *,
    settings: Settings | None = None,
) -> MCPServer:
    backend = QualityMCP(
        root, timeout_seconds=timeout_seconds, settings=settings or Settings()
    )
    server = MCPServer(name="engineering-team-quality", log_level="ERROR")

    @server.tool()
    def run_tests(role: str, paths: list[str] | None = None) -> dict[str, Any]:
        return _wire_result("quality", backend.run_tests, AgentRole(role), paths)

    @server.tool()
    def get_test_results(role: str) -> dict[str, Any]:
        return _wire_result("quality", backend.get_test_results, AgentRole(role))

    @server.tool()
    def run_build(role: str) -> dict[str, Any]:
        return _wire_result("quality", backend.run_build, AgentRole(role))

    @server.tool()
    def get_build_status(role: str) -> dict[str, Any]:
        return _wire_result("quality", backend.get_build_status, AgentRole(role))

    @server.tool()
    def run_linter(role: str) -> dict[str, Any]:
        return _wire_result("quality", backend.run_linter, AgentRole(role))

    @server.tool()
    def scan_dependencies(role: str) -> dict[str, Any]:
        return _wire_result("quality", backend.scan_dependencies, AgentRole(role))

    @server.tool()
    def run_security_scan(role: str) -> dict[str, Any]:
        return _wire_result("quality", backend.run_security_scan, AgentRole(role))

    @server.tool()
    def get_security_report(role: str) -> dict[str, Any]:
        return _wire_result("quality", backend.get_security_report, AgentRole(role))

    return server


def settings_from_arguments(*, runner: str, image: str, stack: str = "python") -> Settings:
    """Settings for a server told what to be, rather than left to infer it.

    The file-based settings still load, so everything else behaves as it does in
    the parent; only the choices that must not be lost are overridden.
    """
    return Settings(quality_runner=runner, quality_container_image=image, quality_stack=stack)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("repository", "quality"), required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--timeout", type=float, default=60)
    # Passed explicitly because the MCP SDK launches this process with a scrubbed
    # environment -- HOME, LOGNAME, PATH, SHELL, USER and nothing else -- so a
    # setting given as an environment variable never arrives.
    parser.add_argument("--runner", default="process")
    parser.add_argument("--image", default="")
    # ADR 4: which ecosystem's commands to run, and where that component lives
    # relative to --root. Both explicit, like --runner and --image: a repository
    # with more than one buildable component (finding 19) has no single correct
    # guess. Unused by the repository server, which always sees the whole tree.
    parser.add_argument("--stack", default="python")
    parser.add_argument("--component-root", default="")
    args = parser.parse_args()
    if args.kind == "repository":
        server = build_repository_server(args.root)
    else:
        quality_root = (
            Path(args.root) / args.component_root if args.component_root else Path(args.root)
        )
        server = build_quality_server(
            quality_root, args.timeout,
            settings=settings_from_arguments(
                runner=args.runner, image=args.image, stack=args.stack
            ),
        )
    server.run("stdio")


if __name__ == "__main__":
    main()
