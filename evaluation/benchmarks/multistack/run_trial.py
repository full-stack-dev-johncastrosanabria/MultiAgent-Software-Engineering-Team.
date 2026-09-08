"""Run an authorized real benchmark, recording a minimum three-minute experiment gap."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from engineering_team.apply_run import run_on_project
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.guardrails.secrets import redact_secrets
from engineering_team.llm.cloud import CloudRouter

def _anonymised_path(value: str | None) -> str | None:
    """A PATH-like value with the operator's home directory replaced by `~`.

    Whether docker resolves at all is the diagnostic worth keeping; the absolute
    location of the home directory only names the person who ran the trial, and
    an evidence packet is written to be shared. `redact_secrets` looks for
    credential keys and would not touch a home directory, so the substitution is
    made here and the redactor still runs for a PATH entry that embeds one.
    """
    if not value:
        return value
    home = str(Path.home())
    entries = []
    for entry in value.split(os.pathsep):
        if entry == home or entry.startswith(home + os.sep):
            entry = "~" + entry[len(home):]
        entries.append(redact_secrets(entry))
    return os.pathsep.join(entries)


CASES = {
    "ingresos": ("PruebaNuevosIngresosBackend", "jvm", "order-ms"),
    "northgate": ("NorthgateTollPlaza", "jvm", "northgate-backend"),
    "interview": ("InterviewCleanApi", "dotnet", ""),
}


def require_experiment_interval(records: list[dict], probes: dict, now: float) -> None:
    if any(item.get("finished_epoch") is None for item in records):
        raise SystemExit("Prior experiment has no terminal record; inspect it before retrying.")
    last_finished = max(
        [item["ended_epoch"] for item in probes["attempts"]]
        + [item["finished_epoch"] for item in records],
        default=float("-inf"),
    )
    remaining = 180 - (now - last_finished)
    if remaining > 0:
        raise SystemExit(f"Experiment interval: wait at least {remaining:.1f} more seconds.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=CASES)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--test-arg", action="append")
    parser.add_argument("--confirm-delivery", action="store_true")
    args = parser.parse_args()
    if args.report.exists():
        parser.error("Choose a new report path; existing experiment evidence is preserved.")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    # All repository cases in this workspace share one lock and journal,
    # regardless of where each caller chooses to write its report.
    state_dir = args.workspace.resolve() / "evidence"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "experiments.json"
    with (state_dir / "experiments.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        records = json.loads(state_path.read_text()) if state_path.exists() else []
        probes = json.loads(Path(__file__).with_name("gemini-key2-probes.json").read_text())
        require_experiment_interval(records, probes, time.time())
        record = {
            "case": args.case,
            "started_epoch": time.time(),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "report": str(args.report.resolve()),
            "finished_epoch": None,
        }
        records.append(record)
        state_path.write_text(json.dumps(records, indent=2))
        try:
            repo, stack, component = CASES[args.case]
            settings = Settings(
                quality_runner="container", quality_stack=stack,
                quality_component_path=component, quality_timeout_seconds=900,
                cloud_role_timeout_seconds=180, llm_timeout_seconds=60,
                max_remediation_iterations=3,
                langfuse_public_key=None, langfuse_secret_key=None,
                delivery_backend="gh" if args.confirm_delivery else "none",
            )
            if settings.gemini_api_key_2:
                router = CloudRouter(settings)
                for role in (AgentRole.PRODUCT, AgentRole.ARCHITECTURE,
                             AgentRole.DEVELOPER, AgentRole.SECURITY):
                    chain = [f"{s.provider}:{s.model}" for s in router.selection_chain(role)]
                    chain.append("google2:gemini-3.1-flash-lite")
                    setattr(settings, f"cloud_chain_{role.value.lower()}", ",".join(chain))
            evidence = run_on_project(
                settings, project_path=args.workspace / repo,
                specification=Path(__file__).with_name(f"{args.case}.md").read_text(),
                authorize_writes=True, test_paths=args.test_arg,
                report_path=args.report, confirm_delivery=args.confirm_delivery,
            )
            record["final_status"] = evidence.get("final_status")
            print(json.dumps({k: evidence.get(k) for k in (
                "run_id", "final_status", "files_written", "errors", "delivery_pr_url"
            )}), flush=True)
        except BaseException as exc:
            record["exception_type"] = type(exc).__name__
            record["final_status"] = "ERROR"
            # Persist enough to discriminate ServiceStartupError raise sites and
            # PATH/docker resolution without leaking secrets into evidence.
            tb = traceback.extract_tb(exc.__traceback__)
            raise_frame = tb[-1] if tb else None
            raise_site = (
                f"{raise_frame.filename}:{raise_frame.lineno} in {raise_frame.name}"
                if raise_frame is not None
                else None
            )
            docker_path = shutil.which("docker")
            capture = {
                "benchmark_case": args.case,
                "final_status": "ERROR",
                "exception_type": type(exc).__name__,
                "exception_message": redact_secrets(str(exc)),
                "raise_site": raise_site,
                "process_path": _anonymised_path(os.environ.get("PATH", "")),
                "docker_which": _anonymised_path(docker_path),
                "started_utc": record["started_utc"],
            }
            record["exception_message"] = capture["exception_message"]
            record["raise_site"] = raise_site
            record["docker_which"] = capture["docker_which"]
            if not args.report.exists():
                args.report.write_text(json.dumps(capture, indent=2))
            raise
        finally:
            record["finished_epoch"] = time.time()
            state_path.write_text(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
