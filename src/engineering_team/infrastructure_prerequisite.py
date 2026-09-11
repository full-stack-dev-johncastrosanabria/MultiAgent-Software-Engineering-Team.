"""Infrastructure a run needs and the project does not declare.

[ADR 18](../../docs/architecture/decisions/0018-infrastructure-is-a-blocking-prerequisite.md)
decides that this case is a blocking prerequisite: the run delivers the
infrastructure as its own pull request, brings it up, and proceeds on top of it
-- rather than conjuring a database for ten minutes and leaving it on the
operator's laptop, which is what produced the unlabelled `icapi-mysql` container
that record is written against.

Almost none of the analysis is new here. `ServicesMCP` already infers a topology
from the connection strings a project declares, already renders a developer-facing
compose file and `.env.example` (`delivery_artifacts`), and `infrastructure_proposal`
already turns those into something a person can review. What was missing is that
the inference was *thrown away*: `down()` deleted the derived file and the next
run inferred it again. This module is the second consumer ADR 18 says that
analysis acquires.

What it adds beyond plumbing is the honesty the functional delivery then owes.
When functional work runs against infrastructure this same run authored, its
evidence describes an environment no human has approved yet, and if a reviewer
edits the compose file before merging it, that evidence describes an environment
that no longer exists. `stacked_body` is what makes the second pull request say
so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engineering_team.delivery import (
    DeliveryRefused,
    GitDelivery,
    Proposal,
    infrastructure_proposal,
)

__all__ = [
    "DeliveredInfrastructure",
    "Prerequisite",
    "deliver",
    "detect",
    "stacked_body",
]


@dataclass(frozen=True)
class Prerequisite:
    """Infrastructure the project needs and does not declare."""

    engines: tuple[str, ...]
    read_from: tuple[str, ...]
    """The project's own files the values were read from, named in the body."""
    compose: str
    env_example: str

    def proposal(self, run_id: str) -> Proposal | None:
        return infrastructure_proposal(
            self.compose,
            self.env_example,
            run_id=run_id,
            engines=self.engines,
            read_from=self.read_from,
        )


@dataclass(frozen=True)
class DeliveredInfrastructure:
    """What the infrastructure pull request left behind for the functional one."""

    branch: str
    engines: tuple[str, ...]
    url: str = ""


def detect(services: Any, root: str | Path) -> Prerequisite | None:
    """Whether this run is standing on infrastructure the project never declared.

    ADR 18 leaves the detecting signal to the implementation and says the first
    version will be narrower than the rule. This is that narrow version, and the
    signal is the one already computed: a topology that had to be *derived*
    means the project declares nothing and the run is about to run on something
    that exists only for the next ten minutes. A failed connection would catch
    more cases; it is not needed to catch this one, which is the case that
    produced the evidence in the record.

    A project that declares its own compose file is not a prerequisite, and
    neither is one that needs no services at all: both produce `None`, which is
    the right answer rather than an empty pull request.
    """
    if not getattr(services, "derived", False):
        return None
    compose, env_example = services.delivery_artifacts()
    if not compose.strip():
        return None
    engines = tuple(getattr(services, "services", ()) or ())
    if not engines:
        return None
    return Prerequisite(
        engines=engines,
        read_from=_sources_that_named_the_engines(root, engines),
        compose=compose,
        env_example=env_example,
    )


def _sources_that_named_the_engines(
    root: str | Path, engines: tuple[str, ...]
) -> tuple[str, ...]:
    """Which of the project's files the inference actually read a value from.

    PR #1 said where its values came from, and that sentence is most of why the
    pull request was reviewable. Listing every configuration file scanned would
    be the opposite -- so only files whose text mentions an engine are named.
    """
    from engineering_team.services import configuration_sources

    try:
        sources = configuration_sources(Path(root))
    except OSError:
        return ()
    named = [
        name for name, text in sources.items()
        if any(engine in text.lower() for engine in engines)
    ]
    return tuple(sorted(named))


def deliver(
    repository: str | Path,
    prerequisite: Prerequisite,
    *,
    run_id: str,
    backend: Any | None,
    confirmed: bool,
    git: GitDelivery | None = None,
) -> DeliveredInfrastructure:
    """Open the pull request that contains infrastructure and nothing else.

    Raises `DeliveryRefused` rather than degrading: ADR 18's rule is that
    infrastructure is *either delivered or refused*, and a silent failure here
    would put the run back on the improvised path the record exists to close.
    """
    proposal = prerequisite.proposal(run_id)
    if proposal is None:
        raise DeliveryRefused("the derived topology produced nothing to propose")
    branch = (git or GitDelivery()).push(
        Path(repository), proposal, confirmed=confirmed
    )
    url = ""
    open_pull_request = getattr(backend, "open", None)
    if callable(open_pull_request):
        url = open_pull_request(Path(repository), proposal, confirmed=confirmed)
    return DeliveredInfrastructure(
        branch=branch, engines=prerequisite.engines, url=url
    )


def stacked_body(body: str, delivered: DeliveredInfrastructure) -> str:
    """State what the functional evidence is worth, in the body, not in a note.

    ADR 18: the suite ran green against infrastructure nobody has reviewed. A
    reviewer who changes the compose file before merging it invalidates the
    evidence recorded here, and has to know to ask for a re-run. Saying this
    plainly is the condition on which the stacked pull request is allowed to
    claim its suite passed.
    """
    reference = delivered.url or f"`{delivered.branch}`"
    named = ", ".join(delivered.engines)
    return (
        f"{body}\n\n"
        "---\n\n"
        f"**Stacked on {reference}.** This project declared no infrastructure, so "
        f"this run authored it ({named}) and opened it as a separate pull request "
        "first. This branch is cut from that one and merges into it, not into the "
        "default branch.\n\n"
        "**What the evidence below is worth.** The suite ran green against "
        "infrastructure that no human has reviewed yet. If that pull request is "
        "changed before it is merged -- a different engine version, different "
        "credentials, a different port -- the results recorded here describe an "
        "environment that no longer exists, and this branch should be re-run "
        "before it is merged."
    )
