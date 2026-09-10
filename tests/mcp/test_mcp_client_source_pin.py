"""MCP child must load the same engineering_team tree as the parent process.

`fp-mcp-isolated-loads-main`: `python -I -m engineering_team.mcp.server` ignored
PYTHONPATH and resolved MAIN (no D2) while the trial parent used a worktree.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import engineering_team
from engineering_team.mcp.client import (
    MCPQualityClient,
    _parent_aset_src,
)


def test_parent_aset_src_is_the_loaded_package_src() -> None:
    expected = Path(engineering_team.__file__).resolve().parents[1]
    assert _parent_aset_src() == expected
    assert (_parent_aset_src() / "engineering_team").is_dir()


def test_parameters_keep_isolation_and_pin_parent_src(tmp_path: Path) -> None:
    args = MCPQualityClient(tmp_path)._parameters().args
    assert args[0] == "-I"
    assert args[1] == "-c"
    bootstrap = args[2]
    src = str(_parent_aset_src())
    assert src in bootstrap
    assert "-m" not in args[:4]
    assert "--kind" in args
    assert args[args.index("--kind") + 1] == "quality"


def test_bootstrap_child_loads_parent_src_not_main_only() -> None:
    """A -I child with the bootstrap must import the runner from the pinned src."""
    src = _parent_aset_src()
    probe = (
        "import sys, json;"
        f"sys.path.insert(0, {json.dumps(str(src))});"
        "import engineering_team.mcp.container as c;"
        "print(json.dumps({"
        "'file': c.__file__,"
        "'api': sorted(n for n in dir(c.ContainerRunner) if not n.startswith('__'))"
        "}))"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout.strip())
    assert Path(payload["file"]).resolve().is_relative_to(src.resolve())
    # Path alone shows where the child read from; the API shows it read the same
    # revision this process did, which is what a worktree can differ on.
    import engineering_team.mcp.container as parent

    assert payload["api"] == sorted(
        name for name in dir(parent.ContainerRunner) if not name.startswith("__")
    )
