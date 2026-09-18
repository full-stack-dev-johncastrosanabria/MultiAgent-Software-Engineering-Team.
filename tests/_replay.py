"""Loader for the frozen replay fixtures under ``tests/fixtures/replay/``.

A plain module rather than a ``conftest.py``, for the same reason ``_docker.py``
is one: the test files that replay a trace import ``load_trace`` explicitly, so
the dependency is visible at the top of each file.

The fixtures hold what four real 2026-09-16 runs actually decided, extracted
from the Langfuse export's AGENT observations and redacted before freezing.
They are evidence, not test data: nothing here may be hand-edited. When a
contract gains or renames a field the fixture stops validating -- that is the
intended failure, and the answer is to re-freeze it from the export.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from engineering_team.contracts.models import (
    ArchitectureProposal,
    ProductSpecification,
    ReviewerDecision,
)

_DIR = Path(__file__).parent / "fixtures" / "replay"


class ReplayFixtureError(RuntimeError):
    """A frozen fixture no longer matches the contracts it was frozen against."""


@dataclass(frozen=True)
class ReplayCycle:
    """One remediation cycle of a real run."""

    cycle: int
    reviewer_decision: ReviewerDecision
    architecture: ArchitectureProposal | None


@dataclass(frozen=True)
class ReplayTrace:
    """Every cycle of one real run, plus the specification it worked from."""

    trace_id: str
    run_name: str
    reproduces: str
    source: str
    specification: ProductSpecification
    cycles: tuple[ReplayCycle, ...]


def _validated(model, payload, where):
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise ReplayFixtureError(
            f"{where} no longer validates as {model.__name__}. This fixture is frozen "
            f"evidence from a real run: re-freeze it from the trace export rather than "
            f"editing it to fit the new contract.\n{error}"
        ) from error


def load_trace(label: str) -> ReplayTrace:
    """Read one frozen trace, validating every artifact against its contract."""
    path = _DIR / f"{label}.json"
    if not path.is_file():
        raise ReplayFixtureError(f"no frozen replay fixture at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return ReplayTrace(
        trace_id=data["trace_id"],
        run_name=data["run_name"],
        reproduces=data["reproduces"],
        source=data["source"],
        specification=_validated(
            ProductSpecification, data["specification"], f"{label}.specification"
        ),
        cycles=tuple(
            ReplayCycle(
                cycle=entry["cycle"],
                reviewer_decision=_validated(
                    ReviewerDecision,
                    entry["reviewer_decision"],
                    f"{label}.cycles[{entry['cycle']}].reviewer_decision",
                ),
                architecture=(
                    _validated(
                        ArchitectureProposal,
                        entry["architecture"],
                        f"{label}.cycles[{entry['cycle']}].architecture",
                    )
                    if entry["architecture"] is not None
                    else None
                ),
            )
            for entry in data["cycles"]
        ),
    )
