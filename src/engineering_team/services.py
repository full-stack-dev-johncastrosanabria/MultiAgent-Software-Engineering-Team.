"""The services a project needs in order to run (ADR 5).

Five of the six repositories this system targets expect a database already
running on a developer's machine, which is exactly what an autonomous agent does
not have. The sixth ships a compose file that declares its whole topology --
images, healthchecks and startup order -- written by people who know the project.
Where that file exists it *is* the topology; nothing here infers one.

Compose does the lifecycle. This module decides what to start, and writes the
override that makes starting it safe: an internal network with no route out, and
no ports published onto the host.

Parsing is delegated to `docker compose config`, which is the same parser that
will later run the file. That also avoids reintroducing pyyaml, deliberately
removed in finding 2.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from engineering_team.contracts.enums import ErrorCode

# The order compose itself resolves them in; the canonical name wins.
COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)
_CONFIG_TIMEOUT_SECONDS = 60
# Compose's own grammar for a service name. Names reach the override document, so
# anything outside this is refused rather than written into a YAML file.
_SERVICE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


class ComposeError(RuntimeError):
    """The project's compose file could not be read or understood."""


class ServiceStartupError(RuntimeError):
    """A service the project depends on never became ready.

    Carries INFRASTRUCTURE_ERROR so the run records that the code under test was
    never given a chance, rather than attributing the outcome to it.
    """

    code = ErrorCode.INFRASTRUCTURE_ERROR


@dataclass(frozen=True)
class ServiceTopology:
    """What a compose file declares, split by who wrote the image."""

    infrastructure: tuple[str, ...]
    """Services the project depends on: a database, a broker, a cache."""

    application: tuple[str, ...]
    """Services built from the repository's own Dockerfiles."""


def find_compose_file(root: Path) -> Path | None:
    """The project's compose file, or None if it does not declare one."""
    for name in COMPOSE_FILENAMES:
        candidate = Path(root) / name
        if candidate.is_file():
            return candidate
    return None


def read_compose_model(compose_file: Path) -> dict:
    """Resolve a compose file through compose's own parser."""
    try:
        completed = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=_CONFIG_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ComposeError(f"compose could not read {compose_file.name}") from exc
    if completed.returncode != 0:
        raise ComposeError(
            f"compose rejected {compose_file.name}: {completed.stderr.strip()[-400:]}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ComposeError(f"compose returned no model for {compose_file.name}") from exc


def classify_services(model: dict) -> ServiceTopology:
    """Split declared services into what we start and what we refuse to build.

    A service carrying `build:` is the project's own code. Starting it would mean
    executing a Dockerfile from a repository nobody on this side audited, and the
    tests do not need it: they run in the component's own container and reach the
    dependencies over the internal network.
    """
    infrastructure: list[str] = []
    application: list[str] = []
    for name, service in (model.get("services") or {}).items():
        (application if service.get("build") else infrastructure).append(name)
    return ServiceTopology(tuple(sorted(infrastructure)), tuple(sorted(application)))


def network_names(model: dict) -> tuple[str, ...]:
    """Every network the override has to close.

    A project that names its own network -- and the one repository of six that
    ships a compose file does -- never touches `default`, so marking only
    `default` internal closes a network nothing is attached to and leaves the
    services with a route out. External networks are excluded: they belong to
    something else and compose refuses to redefine them.
    """
    declared = {
        name
        for name, spec in (model.get("networks") or {}).items()
        if not (spec or {}).get("external")
    }
    for service in (model.get("services") or {}).values():
        declared |= set(service.get("networks") or {})
    return tuple(sorted(declared)) or ("default",)


def override_document(
    services: tuple[str, ...],
    networks: tuple[str, ...] = ("default",),
    project: str = "",
) -> str:
    """The override compose is given as its second `-f`.

    Emitted as YAML because `!override` is a YAML tag with no JSON spelling, and
    the distinction matters: measured against compose, a plain empty `ports` list
    merges with the project's and leaves the published port in place, while
    `!override []` removes it. Writing four keys of YAML needs no library --
    parsing is what finding 2 removed pyyaml for.
    """
    for name in (*services, *networks):
        if not _SERVICE_NAME.match(name):
            raise ComposeError(f"refusing to override a name like {name!r}")
    lines = ["services:"]
    for name in services:
        # `!override` and not an empty list: an empty list would be merged.
        lines += [f"  {name}:", "    ports: !override []"]
    lines.append("networks:")
    for name in networks or ("default",):
        lines.append(f"  {name}:")
        if project:
            # A compose file may pin a global network name -- the one repository
            # of six that ships one does. Two runs would then share a network and
            # either one's teardown would remove it under the other.
            lines.append(f"    name: {project}-{name}")
        lines.append("    internal: true")
    lines.append("")
    return "\n".join(lines)


_PROJECT_NAME = re.compile(r"[^a-z0-9-]+")


class ServiceStack:
    """The project's dependencies, started for the length of one run.

    Compose owns the lifecycle: it already knows the images, the healthchecks and
    the startup order, and `--wait` blocks until every service reports healthy
    rather than sleeping for a guess. What this adds is the override that closes
    the network and the ports, and the decision to start infrastructure only.
    """

    def __init__(self, root: str | Path, run_id: str, *, runtime: str = "docker") -> None:
        self.root = Path(root).resolve()
        self.runtime = runtime
        self.project = "aset-" + _PROJECT_NAME.sub("-", run_id.lower()).strip("-")
        self._compose_file = find_compose_file(self.root)
        self._services: tuple[str, ...] = ()
        self._networks: tuple[str, ...] = ("default",)
        self._network: str | None = None
        self._override: Path | None = None
        self._running = False
        if self._compose_file is not None:
            model = read_compose_model(self._compose_file)
            self._services = classify_services(model).infrastructure
            self._networks = network_names(model)

    @property
    def declared(self) -> bool:
        """Whether the project declares its own topology."""
        return self._compose_file is not None

    @property
    def services(self) -> tuple[str, ...]:
        return self._services

    @property
    def network(self) -> str | None:
        """The network the services actually joined, once they are up.

        Read back from a running container rather than derived from the project
        name: compose only calls it `<project>_default` when the file does not
        name its own, and assuming that produced a name no container was on.
        """
        return self._network

    def up(self, deadline: float) -> None:
        """Start the project's dependencies and wait for them to report healthy."""
        if not self._services or self._compose_file is None:
            return
        descriptor, name = tempfile.mkstemp(suffix="-aset-override.yml", text=True)
        with os.fdopen(descriptor, "w", encoding="utf-8") as writer:
            writer.write(
                override_document(self._services, self._networks, self.project)
            )
        self._override = Path(name)
        completed = self._compose(
            ["up", "-d", "--wait", *self._services],
            timeout=max(1.0, deadline - time.monotonic()),
        )
        if completed is None or completed.returncode != 0:
            detail = "" if completed is None else completed.stderr.strip()[-600:]
            raise ServiceStartupError(
                f"services did not become ready: {detail or 'no output'}"
            )
        self._running = True
        self._network = self._discover_network()
        if self._network is None:
            raise ServiceStartupError("services started on no discoverable network")

    def down(self) -> None:
        """Remove the containers, the volumes and the network this run created."""
        if self._compose_file is not None:
            self._compose(["down", "-v", "--remove-orphans"], timeout=180)
        self._running = False
        if self._override is not None:
            self._override.unlink(missing_ok=True)
            self._override = None

    def _discover_network(self) -> str | None:
        """Ask a running service which network it is on."""
        listed = self._compose(["ps", "-q", *self._services], timeout=60)
        if listed is None or listed.returncode != 0:
            return None
        identifiers = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        for identifier in identifiers:
            inspected = subprocess.run(
                [self.runtime, "inspect", "-f",
                 "{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}\n{{end}}",
                 identifier],
                capture_output=True, text=True, timeout=60, check=False,
            )
            for name in inspected.stdout.split():
                if name:
                    return name
        return None

    def _compose(
        self, arguments: list[str], *, timeout: float
    ) -> subprocess.CompletedProcess[str] | None:
        if shutil.which(self.runtime) is None or self._compose_file is None:
            return None
        files = ["-f", str(self._compose_file)]
        if self._override is not None:
            files += ["-f", str(self._override)]
        try:
            return subprocess.run(
                [self.runtime, "compose", "-p", self.project, *files, *arguments],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(arguments, 1, "", str(exc))
