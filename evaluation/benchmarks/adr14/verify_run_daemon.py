"""Exercise ADR 14 against real target suites and retain sanitized evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.guardrails.secrets import redacted_document
from engineering_team.mcp.quality import QualityMCP


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--daemon-image", required=True)
    parser.add_argument("--component", action="append", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"host": platform.platform(), "components": [], "finished": False}
    settings = Settings(
        _env_file=None, quality_runner="container", quality_stack="jvm",
        quality_run_daemon_image=args.daemon_image,
        quality_run_daemon_images=("postgres:17-alpine", "apache/kafka:4.3.1"),
    )
    try:
        for component in args.component:
            source = args.source / component
            root = args.output / "workspace" / component
            shutil.copytree(source, root, ignore=shutil.ignore_patterns("target", ".git"))
            hashes = {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*")) if path.is_file()
            }
            quality = QualityMCP(root, settings=settings, timeout_seconds=900)
            daemon = quality._runner.daemon
            entry = {"component": component, "source_hashes": hashes,
                     "daemon": daemon.name, "network": daemon.network}
            report["components"].append(entry)
            started = time.monotonic()
            try:
                result = quality.run_tests(AgentRole.TESTING)
                entry["result"] = result.model_dump(mode="json")
                if daemon._ready:
                    for label, command in (
                        ("container_inspect", ["docker", "inspect", daemon.name]),
                        ("network_inspect", ["docker", "network", "inspect", daemon.network]),
                        ("nested_containers", ["docker", "exec", daemon.name,
                                               "docker", "--host=tcp://127.0.0.1:2375",
                                               "ps", "-a", "--format", "{{json .}}"]),
                    ):
                        completed = subprocess.run(command, capture_output=True, text=True,
                                                   timeout=30, check=False)
                        entry[label] = {"exit_code": completed.returncode,
                                        "stdout": completed.stdout, "stderr": completed.stderr}
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                quality.close()
                entry["duration_seconds"] = round(time.monotonic() - started, 3)
                for label, command in (
                    ("container_removed", ["docker", "inspect", daemon.name]),
                    ("network_removed", ["docker", "network", "inspect", daemon.network]),
                ):
                    entry[label] = subprocess.run(
                        command, capture_output=True, timeout=30, check=False,
                    ).returncode != 0
            (args.output / "report.json").write_text(
                json.dumps(redacted_document(report), indent=2) + "\n"
            )
            print(json.dumps({"component": component,
                              "status": entry.get("result", {}).get("status"),
                              "error": entry.get("error"),
                              "seconds": entry["duration_seconds"]}), flush=True)
        report["finished"] = True
    finally:
        (args.output / "report.json").write_text(
            json.dumps(redacted_document(report), indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
