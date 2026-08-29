"""Bounded, transport-neutral helpers for repository evidence."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

MAX_ARCHITECTURE_READ_FILES = 4
MAX_ARCHITECTURE_READ_BYTES = 16 * 1024

_EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "node_modules"}


def safe_repository_path(raw_path: str) -> str | None:
    """Normalize a relative, non-secret repository path or reject it.

    Symlink containment remains enforced by RepositoryMCP, which resolves the
    actual filesystem entry. This preflight prevents an untrusted listing from
    asking that boundary to inspect an absolute, traversal, cache, or secret
    path.
    """
    normalized = raw_path.strip().replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in _EXCLUDED_PARTS for part in candidate.parts)
        or any(part == ".env" or part.startswith(".env.") for part in candidate.parts)
    ):
        return None
    return candidate.as_posix()


def bounded_utf8(value: str, limit: int = MAX_ARCHITECTURE_READ_BYTES) -> str:
    """Return at most ``limit`` UTF-8 bytes without splitting a code point."""
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def _paths_from_json(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        paths: list[str] = []
        for item in value:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                path = item.get("path") or item.get("relative_path")
                if isinstance(path, str):
                    paths.append(path)
        return paths
    if isinstance(value, dict):
        for key in ("paths", "files", "items", "entries", "results"):
            if key in value:
                return _paths_from_json(value[key])
    return []


def parse_repository_paths(output_summary: str) -> list[str]:
    """Parse both legacy newline listings and future typed/paginated JSON pages."""
    try:
        parsed = json.loads(output_summary)
    except (json.JSONDecodeError, TypeError):
        candidates = output_summary.splitlines()
    else:
        candidates = _paths_from_json(parsed)
    safe = [path for item in candidates if (path := safe_repository_path(str(item)))]
    return list(dict.fromkeys(safe))


def result_path(input_summary: str) -> str | None:
    if not input_summary.startswith("path="):
        return None
    return safe_repository_path(input_summary.removeprefix("path="))
