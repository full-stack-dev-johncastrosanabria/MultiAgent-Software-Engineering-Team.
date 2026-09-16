"""Conservative applicability of test commands in an unchanged component."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from engineering_team.components import list_repository_paths


def normalized_changes(paths: list[str]) -> tuple[str, ...] | None:
    normalized = []
    for path in paths:
        if not isinstance(path, str) or not path or "\\" in path:
            return None
        candidate = PurePosixPath(path)
        if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts or ":" in path:
            return None
        normalized.append(candidate.as_posix())
    return tuple(normalized)


def undeclared_unchanged_suite(backend: Any, changed_paths: tuple[str, ...] | None) -> str | None:
    """Return an omission reason only when no test command or test source exists.

    Unknown/malformed declarations still run and fail normally. A modified
    component must provide tests even if it had no suite before this change.
    This does not label a nonexistent command as a successful test execution.
    """
    if changed_paths is None or getattr(getattr(backend, "profile", None), "name", "") != "node":
        return None
    if getattr(backend, "test_filter", ""):
        return None
    root = getattr(backend, "root", None)
    workspace = getattr(backend, "workspace_root", None)
    if not isinstance(root, Path) or not isinstance(workspace, Path):
        return None
    try:
        relative = root.resolve().relative_to(workspace.resolve()).as_posix()
        prefix = "" if relative == "." else relative + "/"
        if any(not prefix or path == relative or path.startswith(prefix) for path in changed_paths):
            return None
        manifest = root / "package.json"
        if not manifest.resolve().is_relative_to(root.resolve()):
            return None
        package = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(package, dict):
            return None
        scripts = package.get("scripts", {})
        if not isinstance(scripts, dict) or any(
            re.search(r"(?:^|[:_-])(?:test|tests|spec|e2e)(?:$|[:_-])", name.lower())
            for name in scripts
        ):
            return None
        if set(package) & {"jest", "vitest", "playwright", "cypress", "ava", "mocha", "tap", "nyc"}:
            return None
        for path in list_repository_paths(root):
            parts = PurePosixPath(path.lower()).parts
            if any(part in {"test", "tests", "spec", "specs", "__tests__", "cypress", "e2e"} for part in parts):
                return None
            if re.search(r"(?:^|[._-])(?:test|spec)s?(?:[._-]|$)", parts[-1]):
                return None
            if re.match(r"\.?(?:jest|vitest|playwright|karma|cypress|ava|mocha|tap|nyc)", parts[-1]):
                return None
    except (OSError, ValueError):
        return None
    return f"{relative}: no test command or test sources declared; component unchanged"
