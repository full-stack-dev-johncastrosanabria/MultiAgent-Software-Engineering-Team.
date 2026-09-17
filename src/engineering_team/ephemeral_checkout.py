"""A repository, for exactly as long as one run, and then gone.

The run works against a real clone because delivery pushes from it: a branch and
a remote are what `GitDelivery` needs. What the operator asked for is that the
working copy not survive the run, so the clone lives in a temporary directory
that is removed on the way out -- including when the run raises, which is the
case that actually loses things.

No token passes through this module: a URL carrying `user:token@host` is
refused before it ever reaches `subprocess.run`'s argv (see
`_refuse_a_credentialed_url`), so the clone and the push are left to whatever
credential helper the host already has configured.
"""

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from engineering_team.guardrails.secrets import redact_secrets

_CLONE_TIMEOUT_SECONDS = 600


def _refuse_a_credentialed_url(url: str) -> None:
    """Raise before a URL carrying `user:token@host` reaches argv.

    A caller that hands this module `https://<token>@host/...` has
    misunderstood how it authenticates: the module's contract is that it never
    takes a credential, so silently stripping the userinfo would hide that
    misunderstanding while the token had already sat in this process's argv
    (and stays in the caller's own string regardless). Refusing before
    `subprocess.run` is the only option that keeps the credential out of argv
    entirely.

    `urlsplit` gives an empty `netloc` for both a filesystem path and an
    scp-style address (`git@host:owner/repo.git` has no `scheme://`, so it
    parses entirely as `path`), so neither trips this check -- only a URL with
    an actual `scheme://[user[:token]@]host` netloc can carry a credential
    here. The message names the host, never the userinfo, so a token can never
    reach a log or an exception this way.
    """
    netloc = urlsplit(url).netloc
    if "@" in netloc:
        host = netloc.rsplit("@", 1)[-1]
        raise RuntimeError(
            f"refusing a credentialed URL (host: {host}); ephemeral_checkout "
            "authenticates through the host's own git credential helper, not "
            "through the URL"
        )


@contextmanager
def ephemeral_checkout(url: str, *, depth: int = 1) -> Iterator[Path]:
    """Clone `url` into a temporary directory and yield its root.

    `depth` defaults to a shallow clone: ADR 17's rule is that no agent may
    reason from history, and what delivery needs is a branch and a diff. Pass
    `depth=0` for a full clone when a remote refuses a shallow push.
    """
    _refuse_a_credentialed_url(url)
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
