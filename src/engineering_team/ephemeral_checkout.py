"""A repository, for exactly as long as one run, and then gone.

The run works against a real clone because delivery pushes from it: a branch and
a remote are what `GitDelivery` needs. What the operator asked for is that the
working copy not survive the run, so the clone lives in a temporary directory
that is removed on the way out -- including when the run raises, which is the
case that actually loses things.

No token passes through this module. The clone and the push use whatever
credential helper the host already has configured, so a credential is never in
this process's memory, its argv, or the cloned `.git/config`.
"""

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from engineering_team.guardrails.secrets import redact_secrets

_CLONE_TIMEOUT_SECONDS = 600


@contextmanager
def ephemeral_checkout(url: str, *, depth: int = 1) -> Iterator[Path]:
    """Clone `url` into a temporary directory and yield its root.

    `depth` defaults to a shallow clone: ADR 17's rule is that no agent may
    reason from history, and what delivery needs is a branch and a diff. Pass
    `depth=0` for a full clone when a remote refuses a shallow push.
    """
    directory = tempfile.mkdtemp(prefix="aset-checkout-")
    root = Path(directory) / "project"
    try:
        arguments = ["git", "clone", "--quiet"]
        if depth > 0:
            arguments += ["--depth", str(depth)]
        arguments += [url, str(root)]
        completed = subprocess.run(
            arguments, capture_output=True, text=True,
            timeout=_CLONE_TIMEOUT_SECONDS, check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"clone failed: {redact_secrets(message)}")
        yield root
    finally:
        # `ignore_errors` because a failed clone may leave a partial tree, and a
        # removal that raises here would replace the run's real error with this
        # one.
        shutil.rmtree(directory, ignore_errors=True)
