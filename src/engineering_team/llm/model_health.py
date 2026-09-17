"""Which models keep failing which role, remembered across runs.

A chain is an ordered guess about which model will do a role's job. Runs on
2026-09-16 showed the guess going stale: a model rewrote governed fields on
every Architecture call, another wrote Spring Boot 3 tests for a Boot 4 project
five times in a row. The ledger keeps each model's recent outcomes per role and
moves the error-prone ones to the end of the chain, in their original order.
It never removes a model: a demoted one is still tried when the others fail,
and recent good outcomes bring it back.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engineering_team.contracts.enums import AgentRole

from .registry import ModelSelection

# What the model itself got wrong: its answer, its contract, its time.
_QUALITY = frozenset({
    "governed_contradiction", "schema_validation", "invalid_response", "incomplete_output",
    "ineffective_remediation", "timeout", "request_rejected",
})
# What will not change by asking again.
_HARD = frozenset({"authentication", "model_unavailable"})
# Provider capacity, not model quality: counted, but lightly.
_CAPACITY = frozenset({"rate_limit", "provider_unavailable"})

_MIN_ATTEMPTS = 4
_ERROR_RATE = 0.5
_CAPACITY_WEIGHT = 0.25
_MIN_AUTHORING = 3
_AUTHORING_FAILURE_RATE = 0.6


class ModelHealth:
    def __init__(self, path: str | Path | None, *, window: int = 20) -> None:
        self.path = Path(path) if path else None
        self.window = window
        self.entries: dict[str, dict[str, list[str]]] = self._load()

    # -- recording ---------------------------------------------------------

    def record_attempt(self, role: AgentRole, provider: str, model: str, category: str | None) -> None:
        self._append(role, provider, model, "attempts", category or "ok")

    def record_authoring(self, role: AgentRole, provider: str, model: str, *, passed: bool) -> None:
        self._append(role, provider, model, "authoring", "pass" if passed else "fail")

    # -- ordering ------------------------------------------------------------

    def ordered(self, role: AgentRole, chain: Sequence[ModelSelection]) -> tuple[ModelSelection, ...]:
        healthy = [item for item in chain if not self.demoted(role, item.provider, item.model)]
        demoted = [item for item in chain if self.demoted(role, item.provider, item.model)]
        demoted.sort(key=lambda item: self.penalty(role, item.provider, item.model))
        return tuple(healthy + demoted)

    def demoted(self, role: AgentRole, provider: str, model: str) -> bool:
        entry = self.entries.get(self._key(role, provider, model), {})
        attempts = entry.get("attempts", [])
        if sum(outcome in _HARD for outcome in attempts) >= 2:
            return True
        if len(attempts) >= _MIN_ATTEMPTS and self._error_rate(attempts) >= _ERROR_RATE:
            return True
        authoring = entry.get("authoring", [])
        return (
            len(authoring) >= _MIN_AUTHORING
            and authoring.count("fail") / len(authoring) >= _AUTHORING_FAILURE_RATE
        )

    def penalty(self, role: AgentRole, provider: str, model: str) -> float:
        entry = self.entries.get(self._key(role, provider, model), {})
        authoring = entry.get("authoring", [])
        authoring_rate = authoring.count("fail") / len(authoring) if authoring else 0.0
        return self._error_rate(entry.get("attempts", [])) + authoring_rate

    # -- storage ---------------------------------------------------------------

    @staticmethod
    def _key(role: AgentRole, provider: str, model: str) -> str:
        return f"{role.value}|{provider}|{model}"

    @staticmethod
    def _error_rate(attempts: list[str]) -> float:
        if not attempts:
            return 0.0
        weight = sum(
            1.0 if outcome in _QUALITY or outcome in _HARD
            else _CAPACITY_WEIGHT if outcome in _CAPACITY
            else 0.0
            for outcome in attempts
        )
        return weight / len(attempts)

    def _append(self, role: AgentRole, provider: str, model: str, kind: str, outcome: str) -> None:
        entry = self.entries.setdefault(self._key(role, provider, model), {})
        history = entry.setdefault(kind, [])
        history.append(outcome)
        del history[:-self.window]
        self._save()

    def _load(self) -> dict[str, dict[str, list[str]]]:
        if self.path is None:
            return {}
        try:
            payload: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, dict):
            return {}
        return {
            str(key): {
                kind: [str(outcome) for outcome in history][-self.window:]
                for kind, history in value.items()
                if kind in {"attempts", "authoring"} and isinstance(history, list)
            }
            for key, value in entries.items() if isinstance(value, dict)
        }

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".model-health-")
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"entries": self.entries}, stream, indent=1, sort_keys=True)
            os.replace(temporary, self.path)
        except OSError:
            # A ledger that cannot be written must never fail the run it describes.
            return
