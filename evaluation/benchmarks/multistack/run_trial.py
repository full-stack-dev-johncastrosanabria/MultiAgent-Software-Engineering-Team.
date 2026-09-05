"""Run an authorized real benchmark, recording a minimum three-minute experiment gap."""

from __future__ import annotations

import argparse
import fcntl
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from engineering_team.apply_run import run_on_project
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.llm.cloud import CloudRouter

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
    state_path = args.report.parent / "experiments.json"
    with (args.report.parent / "experiments.lock").open("a+") as lock:
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
            # A guard or infrastructure exception can precede ASET's normal
            # evidence serializer. Arbitrary exception text can contain secrets.
            if not args.report.exists():
                args.report.write_text(json.dumps({
                    "benchmark_case": args.case,
                    "final_status": "ERROR",
                    "exception_type": type(exc).__name__,
                    "started_utc": record["started_utc"],
                }, indent=2))
            raise
        finally:
            record["finished_epoch"] = time.time()
            state_path.write_text(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
