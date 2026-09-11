"""Validating the compose file that is delivered, not the one the run starts.

[ADR 18](../../docs/architecture/decisions/0018-missing-infrastructure-is-a-blocking-prerequisite.md)
makes infrastructure a pull request. The gap that leaves is that the run never
touches the artefact it proposes: `derive_compose` renders the same inference
twice -- `RUN` addresses services by name on a closed network and publishes
nothing, `DELIVERY` publishes on localhost and replaces every credential with
`${VARIABLE}` backed by a `.env.example`. The run starts the first. The reviewer
receives the second. Everything that differs between them -- the published
ports, the variable substitution, the companion template -- reaches a person
having never been executed.

The failure this closes is not hypothetical and is not exotic: a `DELIVERY`
compose that interpolates `${POSTGRES_PASSWORD}` while the generated
`.env.example` declares a different key produces `required variable
POSTGRES_PASSWORD is missing a value` on the reviewer's machine, and the pull
request that caused it was green here.

Two honesties are owed in return. The first is that this validates the file, not
the system: `compose config` resolves the schema and the substitution, and says
nothing about whether the images start or the healthchecks ever pass. The second
is the synthetic `.env`. Its values are the literal marker
`PLACEHOLDER-FOR-VALIDATION` derived from the *keys* of the template, and
`os.environ` is never read -- an operator's real `POSTGRES_PASSWORD` leaking into
a validation run would make the check pass for a reason the reviewer cannot
reproduce, and would put a credential in a temporary file this module wrote.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from engineering_team.guardrails.secrets import redact_secrets

__all__ = ["PLACEHOLDER", "DeliveryCheck", "validate_delivered_compose"]

PLACEHOLDER = "PLACEHOLDER-FOR-VALIDATION"
"""The only value the synthetic `.env` ever carries.

Literal and recognisable on purpose: if it ever escapes into a message a person
reads, the message says where it came from without anyone having to guess.
"""

_TIMEOUT_SECONDS = 120

# `- "5432:5432"`, with or without a bind address. Only consulted inside a
# `ports:` block, so the `- ./init.sql:/docker-entrypoint-initdb.d/...:ro` a
# volume mount is shaped like cannot be read as a published port.
_PUBLISHED = re.compile(
    r'^\s*-\s*"?(?:\d{1,3}(?:\.\d{1,3}){3}:)?(?P<host>\d+):\d+(?:/\w+)?"?\s*$'
)
# What `docker ps --format {{.Ports}}` prints for a port that is bound on the
# host: `0.0.0.0:5432->5432/tcp`. A container port with no host side prints
# without the arrow and is not a conflict for anybody.
_BOUND = re.compile(r"(?:0\.0\.0\.0|\[::\]|:::):(?P<port>\d+)->")


@dataclass(frozen=True)
class DeliveryCheck:
    """What running the delivered compose file said about it."""

    performed: bool = False
    """False when there is no container runtime here to ask.

    Distinct from `valid=False` and treated differently by the caller: not
    having asked is not the same as having been told no.
    """
    valid: bool = True
    error: str = ""
    """Why the runtime rejected the file, already redacted."""
    occupied_ports: tuple[str, ...] = ()
    """Published ports something on this host is already listening on.

    A warning rather than a refusal. The port is busy *here*; the reviewer's
    machine is a different host, and refusing a correct file because this one
    happens to run a database would be the wrong trade.
    """


def _synthetic_environment(env_example: str) -> str:
    """The keys of the template, with the marker for every value.

    Derived from the template rather than from the process environment. See the
    module docstring: reading `os.environ` here would validate against
    credentials the reviewer does not have and write them to disk besides.
    """
    lines = []
    for line in env_example.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            lines.append(f"{key}={PLACEHOLDER}")
    return "\n".join(lines) + "\n" if lines else ""


def _published_ports(compose: str) -> tuple[str, ...]:
    """The host ports the delivered file asks for, read from the file itself.

    Read from the text rather than from `compose config --format json`: the
    rendering is this system's own, the shape is known, and one subprocess whose
    absence is already handled is easier to reason about than two.
    """
    found: list[str] = []
    inside = False
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("-"):
            inside = stripped == "ports:"
            continue
        if not inside:
            continue
        match = _PUBLISHED.match(line)
        if match and match.group("host") not in found:
            found.append(match.group("host"))
    return tuple(found)


def _ports_already_bound(runtime: str) -> set[str]:
    try:
        completed = subprocess.run(
            [runtime, "ps", "--format", "{{.Ports}}"],
            capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if completed.returncode != 0:
        return set()
    return {match.group("port") for match in _BOUND.finditer(completed.stdout)}


def validate_delivered_compose(
    compose: str, env_example: str, *, runtime: str = "docker"
) -> DeliveryCheck:
    """Ask the runtime whether the file the reviewer receives is usable.

    Partial by construction: this resolves the schema and the variable
    substitution. Whether the images pull, start, or report healthy is not
    asked, and the body of the pull request says so rather than letting a green
    check imply more than it earned.
    """
    if not compose.strip():
        return DeliveryCheck(performed=False)
    if shutil.which(runtime) is None:
        return DeliveryCheck(performed=False)
    with tempfile.TemporaryDirectory(prefix="aset-delivery-check-") as directory:
        root = Path(directory)
        compose_file = root / "docker-compose.yml"
        env_file = root / ".env"
        compose_file.write_text(compose, encoding="utf-8")
        env_file.write_text(_synthetic_environment(env_example), encoding="utf-8")
        try:
            completed = subprocess.run(
                [
                    runtime, "compose",
                    "-f", str(compose_file),
                    "--env-file", str(env_file),
                    "config", "--quiet",
                ],
                capture_output=True, text=True,
                timeout=_TIMEOUT_SECONDS, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            # A runtime on PATH that cannot be spoken to is the same answer as
            # no runtime at all: nothing was learned about the file.
            return DeliveryCheck(performed=False, error=redact_secrets(str(error)))
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        return DeliveryCheck(
            performed=True, valid=False, error=redact_secrets(message)
        )
    bound = _ports_already_bound(runtime)
    return DeliveryCheck(
        performed=True,
        valid=True,
        occupied_ports=tuple(
            port for port in _published_ports(compose) if port in bound
        ),
    )
