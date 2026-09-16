"""Bounded, untrusted path proposals made before Developer authors any code."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field

from engineering_team.contracts.models import StrictModel
from engineering_team.repository_evidence import is_credential_path

MAX_PLAN_PATHS = 12
MAX_INVENTORY_PATHS = 600
MAX_INVENTORY_BYTES = 48 * 1024
_BUILD_PARTS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    "bin", "obj", "dist", "build", "target", "coverage", ".aset",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
}
_SOURCE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".kt", ".go", ".rb",
    ".cs", ".fs", ".vb", ".rs", ".c", ".cpp", ".h", ".hpp", ".swift",
}
_MANIFESTS = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "package.json",
    "pom.xml", "build.gradle", "build.gradle.kts", "go.mod", "Cargo.toml",
}


def safe_plan_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(
        path and len(path.encode()) <= 400 and "\\" not in path and ":" not in path
        and not candidate.is_absolute() and str(candidate) == path
        and not any(part in {".", ".."} for part in candidate.parts)
        and not any(part.casefold() in _BUILD_PARTS for part in candidate.parts)
        and not any(ord(char) < 32 for char in path)
        and not is_credential_path(path)
    )


def is_test_path(path: str) -> bool:
    candidate = PurePosixPath(path.casefold())
    stem = candidate.stem
    original_stem = PurePosixPath(path).stem
    return bool(
        any(part in {"test", "tests", "__tests__"} or part.endswith(".tests")
            for part in candidate.parts[:-1])
        or candidate.name == "conftest.py"
        or stem in {"test", "tests"} or stem.startswith("test_")
        or stem.endswith(("_test", "_tests"))
        or (
            candidate.suffix in {".cs", ".fs", ".vb", ".java", ".kt", ".csproj", ".fsproj", ".vbproj"}
            and (
                original_stem.endswith(("Test", "Tests"))
                or original_stem.startswith("Test") and original_stem[4:5].isupper()
            )
        )
        or ".test." in candidate.name or ".spec." in candidate.name
    )


def is_manifest(path: str) -> bool:
    candidate = PurePosixPath(path)
    return candidate.name in _MANIFESTS or candidate.suffix in {".csproj", ".fsproj", ".vbproj"}


class NewDeveloperFile(StrictModel):
    path: str
    kind: Literal["test_source", "test_project", "test_support"]
    component_root: str


class DeveloperTargetPlan(StrictModel):
    """Inventory is governed input; proposed paths are validated independently."""

    inventory_paths: list[str] = Field(default_factory=list, max_length=MAX_INVENTORY_PATHS)
    component_roots: list[str] = Field(default_factory=list, max_length=MAX_INVENTORY_PATHS)
    protected_test_paths: list[str] = Field(default_factory=list, max_length=MAX_INVENTORY_PATHS)
    read_paths: list[str] = Field(default_factory=list, max_length=MAX_PLAN_PATHS)
    edit_paths: list[str] = Field(default_factory=list, max_length=MAX_PLAN_PATHS)
    new_files: list[NewDeveloperFile] = Field(default_factory=list, max_length=MAX_PLAN_PATHS)


def plan_candidate(paths: list[str], *, authored: set[str]) -> DeveloperTargetPlan:
    inventory: list[str] = []
    size = 0
    for path in dict.fromkeys(paths):
        if not safe_plan_path(path):
            continue
        if len(inventory) >= MAX_INVENTORY_PATHS or size + len(path.encode()) > MAX_INVENTORY_BYTES:
            break
        inventory.append(path)
        size += len(path.encode())
    roots = sorted({str(PurePosixPath(path).parent) for path in inventory if is_manifest(path)})
    return DeveloperTargetPlan(
        inventory_paths=inventory,
        component_roots=roots or ["."],
        protected_test_paths=[path for path in inventory if is_test_path(path) and path not in authored],
    )


def _under(path: str, root: str) -> bool:
    return root == "." or path.startswith(root + "/")


def validate_target_plan(
    candidate: DeveloperTargetPlan, proposed: DeveloperTargetPlan, *, all_paths: set[str],
) -> tuple[list[str], list[str]]:
    """Return exact write/read allowlists, or reject the entire plan before reads/writes."""
    for field in ("inventory_paths", "component_roots", "protected_test_paths"):
        if getattr(proposed, field) != getattr(candidate, field):
            raise ValueError("target plan changed governed inventory")
    inventory = set(candidate.inventory_paths)
    protected = set(candidate.protected_test_paths)
    # In remediation a planner re-proposes the test it wrote last iteration as
    # new. It exists, and is not protected, so it is an edit of that file.
    reproposed = [item.path for item in proposed.new_files
                  if item.path in inventory and item.path not in protected and is_test_path(item.path)]
    new_files = [item for item in proposed.new_files if item.path not in reproposed]
    edit_paths = list(dict.fromkeys([*proposed.edit_paths, *reproposed]))
    existing = [*proposed.read_paths, *edit_paths]
    if any(path not in inventory or not safe_plan_path(path) for path in existing):
        raise ValueError("target plan references an uninspected inventory path")
    if any(path in protected for path in [*edit_paths, *(item.path for item in new_files)]):
        raise ValueError("target plan attempts to modify original tests")
    if any(
        PurePosixPath(path).suffix not in _SOURCE_SUFFIXES
        and not (is_test_path(path) and is_manifest(path))
        for path in edit_paths
    ):
        raise ValueError("target plan edits must be source files")
    new_paths = [item.path for item in new_files]
    writes = [*edit_paths, *new_paths]
    # A remediation may only need a test: coverage can be the one thing missing.
    if not writes or len(writes) > MAX_PLAN_PATHS or len(set(writes)) != len(writes):
        raise ValueError("target plan requires bounded distinct implementation edits")
    test_projects = {
        str(PurePosixPath(item.path).parent) for item in new_files
        if item.kind == "test_project"
    }
    for item in new_files:
        path = item.path
        root = item.component_root
        if root not in candidate.component_roots or not safe_plan_path(path) or path in all_paths:
            raise ValueError("target plan new file is unsafe, existing, or outside a component")
        # A .NET test project may live beside its source project, under a test
        # directory. Other new test files stay inside their declared component.
        in_component = _under(path, root)
        sibling_test = (
            _under(path, str(PurePosixPath(root).parent))
            and any(part.casefold() in {"test", "tests"} or part.casefold().endswith(".tests")
                    for part in PurePosixPath(path).parts[:-1])
        )
        if not in_component and not sibling_test:
            raise ValueError("new test file is outside its component test boundary")
        suffix = PurePosixPath(path).suffix
        if item.kind == "test_project":
            if suffix not in {".csproj", ".fsproj", ".vbproj"} or not is_test_path(path):
                raise ValueError("new test project must be a recognized test manifest")
        elif item.kind == "test_source":
            if suffix not in _SOURCE_SUFFIXES or not is_test_path(path):
                raise ValueError("new test source must have a test path and source extension")
        elif (
            suffix not in _SOURCE_SUFFIXES or not is_test_path(path)
            or PurePosixPath(path).name not in {"conftest.py", "__init__.py", "Usings.cs"}
        ):
            raise ValueError("unsupported test support file")
        if not in_component and not any(_under(path, project) for project in test_projects):
            raise ValueError("sibling tests require their new test project")
    reads = list(dict.fromkeys([*edit_paths, *proposed.read_paths]))
    # Always inspect build conventions and a test example in every edited component.
    edited_roots = {root for root in candidate.component_roots
                    if any(_under(path, root) for path in edit_paths)}
    edited_roots |= {item.component_root for item in new_files}
    manifests = [path for path in candidate.inventory_paths
                 if is_manifest(path) and str(PurePosixPath(path).parent) in edited_roots]
    examples = [path for path in candidate.protected_test_paths
                if any(_under(path, root) for root in edited_roots)][:3]
    reads = list(dict.fromkeys([*reads, *manifests, *examples]))
    if len(reads) > 24:
        raise ValueError("target plan exceeds the evidence read budget")
    return writes, reads
