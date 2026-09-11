"""The repository tool, which no longer knows where the project's files live.

The filesystem half moved to `engineering_team.workspace.contract` when
[ADR 17](../../../docs/architecture/decisions/0017-the-project-lives-in-the-run.md)
named the `Workspace` contract. What stays here is policy: which roles may read
or write, what counts as a change, and how a diff is rendered. A workspace that
decided policy would have to be re-audited once per implementation.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.workspace.contract import (
    EXCLUDED_DIRECTORIES,
    HostWorkspace,
    Workspace,
    is_secret_path,
    refuse_traversal,
)

_READ_ROLES = {AgentRole.ARCHITECTURE, AgentRole.DEVELOPER}
_WRITE_ROLES = {AgentRole.DEVELOPER}

# Kept as module names because callers and tests already import them from here.
_EXCLUDED_DIRECTORIES = EXCLUDED_DIRECTORIES
_is_secret_path = is_secret_path
MAX_LISTED_PATHS = 2_000
MAX_LISTING_BYTES = 256 * 1024


class RepositoryMCP:
    def __init__(
        self, root: str | Path | None = None, *, workspace: Workspace | None = None
    ) -> None:
        # A path is still accepted, and still means the host: every existing
        # caller passes one, and ADR 17 is explicit that the host copy stays
        # until the volume path is measured.
        if workspace is None:
            if root is None:
                raise ValueError("a repository needs a root or a workspace")
            workspace = HostWorkspace(root)
        self.workspace = workspace
        # Only a host-backed workspace has one. Nothing here may assume it does.
        self.root = getattr(workspace, "root", None)
        self._originals: dict[str, str | None] = {}

    def _result(
        self,
        role: AgentRole,
        tool: str,
        status: ToolStatus,
        output: str = "",
        error: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_name=tool,
            allowed_role=role,
            status=status,
            input_summary="safe",
            output_summary=output,
            duration_ms=0,
            error=error,
        )

    def _relative(self, relative: str) -> str:
        """The path as the workspace names it, or a refusal."""
        return str(refuse_traversal(relative))

    def list_files(self, role: AgentRole) -> ToolResult:
        if role not in _READ_ROLES:
            return self._result(role, "list_files", ToolStatus.DENIED, error="role denied")
        return self._result(
            role,
            "list_files",
            ToolStatus.SUCCESS,
            self._bounded_listing(),
        )

    def _bounded_listing(self) -> str:
        """Listado acotado: entra a estado y trazas, no puede crecer con el proyecto."""
        listed: list[str] = []
        used = 0
        total = 0
        for relative in self.workspace.list_paths():
            total += 1
            if len(listed) >= MAX_LISTED_PATHS:
                continue
            entry = str(relative)
            cost = len(entry.encode("utf-8")) + 1
            if used + cost > MAX_LISTING_BYTES:
                continue
            listed.append(entry)
            used += cost
        if total > len(listed):
            listed.append(f"# truncated: {len(listed)} of {total} paths")
        return "\n".join(listed)

    def read_file(self, role: AgentRole, relative: str) -> ToolResult:
        if role not in _READ_ROLES:
            return self._result(role, "read_file", ToolStatus.DENIED, error="role denied")
        try:
            return self._result(
                role,
                "read_file",
                ToolStatus.SUCCESS,
                self.workspace.read(self._relative(relative)),
            )
        except (OSError, ValueError) as exc:
            return self._result(role, "read_file", ToolStatus.DENIED, error=str(exc))

    get_file_content = read_file

    def search_code(self, role: AgentRole, query: str) -> ToolResult:
        if role not in _READ_ROLES:
            return self._result(role, "search_code", ToolStatus.DENIED, error="role denied")
        matches = [str(relative) for relative in self.workspace.search(query)]
        return self._result(role, "search_code", ToolStatus.SUCCESS, "\n".join(matches))

    def create_file(self, role: AgentRole, relative: str, content: str) -> ToolResult:
        return self._write(role, "create_file", relative, content, create=True)

    def update_file(self, role: AgentRole, relative: str, content: str) -> ToolResult:
        return self._write(role, "update_file", relative, content, create=False)

    def _write(
        self, role: AgentRole, tool: str, relative: str, content: str, create: bool
    ) -> ToolResult:
        if role not in _WRITE_ROLES:
            return self._result(role, tool, ToolStatus.DENIED, error="role denied")
        try:
            normalized = self._relative(relative)
            existed = self.workspace.exists(normalized)
            if not create and not existed:
                return self._result(role, tool, ToolStatus.FAIL, error="file not found")
            # Strip trailing WS per line and always end with a newline so LLM
            # omissions cannot loop Reviewer→HITL (apply-474c7045 / apply-30fc75c0).
            lines = [line.rstrip(" \t") for line in content.splitlines()]
            normalized_content = "\n".join(lines) + "\n"
            # Veto whitespace-only churn against an existing file (apply-399a301c /
            # product.py trailing-WS and blank-line noise). Same after normalize,
            # or identical once all whitespace is ignored → SUCCESS no-op: do not
            # write, and do not record a spurious change in `_originals` when this
            # path was not already tracked.
            # A file the workspace cannot decode as text is refused rather than
            # rewritten from a lossy copy of itself: reading it with
            # errors="ignore", as this did while it owned the filesystem, made a
            # binary file look like a whitespace change.
            if existed:
                existing = self.workspace.read(normalized)
                existing_lines = [line.rstrip(" \t") for line in existing.splitlines()]
                normalized_existing = "\n".join(existing_lines) + "\n"
                if (
                    normalized_content == normalized_existing
                    or "".join(normalized_content.split())
                    == "".join(normalized_existing.split())
                ):
                    return self._result(role, tool, ToolStatus.SUCCESS, relative)
            if normalized not in self._originals:
                self._originals[normalized] = (
                    self.workspace.read(normalized) if existed else None
                )
            self.workspace.write(normalized, normalized_content)
            return self._result(role, tool, ToolStatus.SUCCESS, relative)
        except (OSError, ValueError) as exc:
            return self._result(role, tool, ToolStatus.DENIED, error=str(exc))

    def get_diff(self, role: AgentRole) -> ToolResult:
        if role not in _WRITE_ROLES:
            return self._result(role, "get_diff", ToolStatus.DENIED, error="role denied")
        sections: list[str] = []
        for relative, original in self._originals.items():
            current = (
                self.workspace.read(relative)
                if self.workspace.exists(relative)
                else None
            )
            before = [] if original is None else original.splitlines(keepends=True)
            after = [] if current is None else current.splitlines(keepends=True)
            if before == after:
                continue
            sections.extend(difflib.unified_diff(
                before,
                after,
                fromfile="/dev/null" if original is None else f"a/{relative}",
                tofile="/dev/null" if current is None else f"b/{relative}",
                lineterm="",
            ))
        return self._result(role, "get_diff", ToolStatus.SUCCESS, "\n".join(sections))
