"""Verify shallow push support and remove only the ref created by this probe."""

import json
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from engineering_team.ephemeral_checkout import ephemeral_checkout
from engineering_team.guardrails.secrets import redacted_document

REPOSITORY = "https://github.com/full-stack-dev-johncastrosanabria/FlaskApiProduct.git"


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True, text=True, timeout=300, check=False,
    )


def _checked(root: Path, *arguments: str) -> str:
    result = _git(root, *arguments)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout or "git command failed")
    return result.stdout.strip()


def main() -> int:
    branch = f"aset/probe-{uuid.uuid4().hex}"
    ref = f"refs/heads/{branch}"
    report: dict[str, object] = {"repository": REPOSITORY, "branch": branch}
    checkout = None
    try:
        with ephemeral_checkout(REPOSITORY, depth=1) as root:
            checkout = root
            report["is_shallow"] = _checked(root, "rev-parse", "--is-shallow-repository") == "true"
            if not report["is_shallow"]:
                raise RuntimeError("the probe requires a shallow checkout")
            _checked(root, "checkout", "-q", "-b", branch)
            probe = root / ".aset-probe" / f"{uuid.uuid4().hex}.txt"
            probe.parent.mkdir(exist_ok=True)
            probe.write_text("Temporary ASET shallow push probe.\n", encoding="utf-8")
            _checked(root, "add", "--", str(probe.relative_to(root)))
            _checked(root, "-c", "user.email=aset@local", "-c", "user.name=ASET",
                     "commit", "-qm", "test: shallow push probe")
            oid = _checked(root, "rev-parse", "HEAD")
            report["commit"] = oid
            report["changed_files"] = _checked(
                root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
            ).splitlines()
            try:
                # An empty lease requires the remote ref not to exist. Never
                # replace another branch, even in the event of a name collision.
                pushed = _git(root, "push", f"--force-with-lease={ref}:",
                              "origin", f"HEAD:{ref}")
                report["push_returncode"] = pushed.returncode
                report["push_output"] = (pushed.stderr or pushed.stdout).strip()
            finally:
                # Also inspect after an ambiguous push failure or timeout. A
                # deletion lease protects a ref another actor may have moved.
                remote = _checked(root, "ls-remote", "--heads", "origin", ref)
                if remote and remote.split()[0] == oid:
                    deleted = _git(root, "push", f"--force-with-lease={ref}:{oid}",
                                   "origin", f":{ref}")
                    report["cleanup_returncode"] = deleted.returncode
                    report["cleanup_output"] = (deleted.stderr or deleted.stdout).strip()
                elif remote:
                    report["cleanup_error"] = "remote ref has another commit; left untouched"
                report["remote_ref_absent"] = not _checked(
                    root, "ls-remote", "--heads", "origin", ref
                )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report["error"] = str(exc)
    report["checkout_removed"] = checkout is not None and not checkout.exists()
    passed = (
        report.get("is_shallow") is True
        and report.get("push_returncode") == 0
        and report.get("cleanup_returncode") == 0
        and report.get("remote_ref_absent") is True
        and report["checkout_removed"]
        and "error" not in report
    )
    report["passed"] = passed
    report["verdict"] = "shallow push accepted and cleaned" if passed else "probe incomplete or failed"
    destination = Path(__file__).resolve().parent / "results" / "shallow-push.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(redacted_document(report), indent=2) + "\n", encoding="utf-8")
    print(report["verdict"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
