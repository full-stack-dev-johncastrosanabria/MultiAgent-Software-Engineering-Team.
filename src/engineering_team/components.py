"""What a stack profile attaches to.

A component is a directory that carries a build manifest. See
`docs/architecture/decisions/0004-profile-per-component.md` for why this is not a
property of the repository: of the six repositories this system is meant to be
pointed at, none is a single stack, and one of them is Java across seven Maven
modules plus a Python service plus a React frontend.

Detection is the existence of a file and nothing else. It has to stay that way:
asking a model which stack a directory is would make a routing decision depend on
free text, which is the one invariant the whole design rests on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# A manifest inside one of these is a dependency's or a build output's, never the
# project's own. Same discipline the repository listing learned in finding 4,
# extended with the build directories the JVM and .NET toolchains produce.
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
    "target", "bin", "obj", "vendor", "site-packages", ".gradle", "Pods",
})

# Exact filenames that identify a stack.
_MANIFEST_NAMES: dict[str, str] = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "pom.xml": "jvm",
    "build.gradle": "jvm",
    "build.gradle.kts": "jvm",
    "package.json": "node",
    "go.mod": "go",
}
# Extensions that identify a stack. A solution file is deliberately absent: it
# lists projects rather than being something to build in a directory.
_MANIFEST_SUFFIXES: dict[str, str] = {
    ".csproj": "dotnet",
    ".fsproj": "dotnet",
    ".vbproj": "dotnet",
}


@dataclass(frozen=True, order=True)
class Component:
    """One buildable unit: where it lives, what it is, and what said so."""

    path: str
    stack: str
    manifest: str


def manifest_stack(filename: str) -> str | None:
    """The stack a manifest filename identifies, or None if it is not one."""
    stack = _MANIFEST_NAMES.get(filename)
    if stack is not None:
        return stack
    suffix = PurePosixPath(filename).suffix
    return _MANIFEST_SUFFIXES.get(suffix)


def is_excluded(path: str) -> bool:
    """Whether a path sits inside a vendored or generated directory."""
    parts = PurePosixPath(path).parts
    return any(part in EXCLUDED_DIRECTORIES for part in parts[:-1])


def detect_components(paths: list[str]) -> list[Component]:
    """Find every buildable unit among repository-relative paths.

    One directory can hold two stacks and is then two components; two manifests
    of the same stack in one directory are one. Ordering is by path and stack so
    the same repository always produces the same list.
    """
    found: dict[tuple[str, str], Component] = {}
    for raw in paths:
        path = raw.replace("\\", "/").lstrip("./")
        if is_excluded(path):
            continue
        pure = PurePosixPath(path)
        stack = manifest_stack(pure.name)
        if stack is None:
            continue
        directory = str(pure.parent) if str(pure.parent) != "." else ""
        key = (directory, stack)
        if key not in found:
            found[key] = Component(path=directory, stack=stack, manifest=pure.name)
    return sorted(found.values())


def list_repository_paths(project_root: str | Path) -> list[str]:
    """Repository-relative file paths under ``project_root``.

    Honours ``EXCLUDED_DIRECTORIES`` the same way detection does: a manifest
    inside ``node_modules`` or ``target`` is never a component of this project.
    """
    import os

    root = Path(project_root)
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRECTORIES]
        relative_dir = Path(dirpath).relative_to(root)
        for filename in filenames:
            relative = (
                Path(filename) if str(relative_dir) == "." else relative_dir / filename
            )
            paths.append(relative.as_posix())
    return paths


def components_in(project_root: str | Path) -> list[Component]:
    """Every buildable component under a project root (ADR 4).

    Walks the tree, feeds relative paths to ``detect_components``, and returns
    the same deterministic ordering a pre-built path list would.
    """
    return detect_components(list_repository_paths(project_root))
