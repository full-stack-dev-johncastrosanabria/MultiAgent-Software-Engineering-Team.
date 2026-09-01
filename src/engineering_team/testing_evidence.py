"""Telling a break apart from a failure that was expected.

A run reported "failed tests require implementation remediation" and pasted
pytest output. Two of the four failures were tests that had passed before the
change; the other two were new tests for a feature that did not work yet. Those
are different news, and the Developer spent three cycles on the wrong one because
the message treated them the same.

Identifiers are read from the output rather than inferred: pytest already prints
exactly which test failed, and parsing what it says beats guessing from a diff.
"""

from __future__ import annotations

import re

from engineering_team.guardrails.secrets import redact_secrets

# `FAILED path::Class::test - reason` and `path::Class::test PASSED`.
_FAILURE_HEADER = re.compile(r"^_+\s+(.+?)\s+_+\s*$")
_SHORT_SUMMARY = re.compile(r"^=+\s+short test summary info\s+=+\s*$", re.IGNORECASE)
_CAPTURED_OUTPUT = re.compile(r"^-+\s+Captured .+\s+-+\s*$")

MAX_FAILURE_DIAGNOSTICS = 6
MAX_FAILURE_DIAGNOSTIC_BYTES = 768
MAX_FAILURE_DIAGNOSTICS_BYTES = 4096


def _split_failure_entry(entry: str) -> tuple[str, str]:
    """Split pytest's optional reason outside a parametrized node id."""
    bracket_depth = 0
    for index, character in enumerate(entry):
        if character == "[":
            bracket_depth += 1
        elif character == "]" and bracket_depth:
            bracket_depth -= 1
        elif bracket_depth == 0 and entry.startswith(" - ", index):
            return entry[:index].strip(), entry[index + 3:].strip()
    return entry.strip(), ""


def _failed_entries(output: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("FAILED "):
            continue
        identifier, detail = _split_failure_entry(stripped.removeprefix("FAILED "))
        if "::" in identifier:
            entries.append((identifier, detail))
    return entries


def failing_tests(output: str) -> tuple[str, ...]:
    """The identifiers pytest reported as failures, in the order printed."""
    return tuple(dict.fromkeys(identifier for identifier, _ in _failed_entries(output)))


def _bounded_utf8(value: str, limit: int) -> str:
    encoded = value.encode()
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode(errors="ignore")


def _pytest_failure_blocks(output: str) -> list[tuple[str, str]]:
    """Return pytest long-report blocks without captured stdout/stderr."""
    lines = output.splitlines()
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _FAILURE_HEADER.match(line)
        if match:
            starts.append((index, match.group(1).strip()))
    blocks: list[tuple[str, str]] = []
    for position, (start, label) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        selected: list[str] = []
        for line in lines[start + 1:end]:
            if _SHORT_SUMMARY.match(line) or _CAPTURED_OUTPUT.match(line):
                break
            if line.strip():
                selected.append(line.rstrip())
        if selected:
            blocks.append((label, "\n".join(selected)))
    return blocks


def _pytest_labels(identifier: str) -> tuple[str, ...]:
    nodes = identifier.split("::")[1:]
    if not nodes:
        return ()
    return tuple(dict.fromkeys((".".join(nodes), nodes[-1])))


def failure_diagnostics(
    output: str, failures: tuple[str, ...]
) -> dict[str, str]:
    """Associate failed pytest node ids with bounded, redacted long reports."""
    blocks = _pytest_failure_blocks(output)
    used: set[int] = set()
    summary_details = {
        identifier: detail for identifier, detail in _failed_entries(output) if detail
    }
    diagnostics: dict[str, str] = {}
    remaining = MAX_FAILURE_DIAGNOSTICS_BYTES
    for identifier in failures[:MAX_FAILURE_DIAGNOSTICS]:
        diagnostic = ""
        labels = _pytest_labels(identifier)
        for index, (label, block) in enumerate(blocks):
            if index not in used and label in labels:
                diagnostic = block
                used.add(index)
                break
        if not diagnostic:
            diagnostic = summary_details.get(identifier, "")
        if not diagnostic or remaining <= 0:
            continue
        redacted = redact_secrets(diagnostic)
        bounded = _bounded_utf8(
            redacted, min(MAX_FAILURE_DIAGNOSTIC_BYTES, remaining)
        )
        if bounded:
            diagnostics[identifier] = bounded
            remaining -= len(bounded.encode())
    return diagnostics


def passing_tests(output: str) -> tuple[str, ...]:
    """The identifiers pytest reported as passing.

    Needs `-v`, which is why a baseline run asks for it: the compact form prints
    dots and a summary, and a dot names nothing.
    """
    identifiers: list[str] = []
    for line in (output or "").splitlines():
        stripped = line.strip()
        marker = stripped.rfind(" PASSED")
        if marker > 0:
            identifier = stripped[:marker].strip()
            if "::" in identifier:
                identifiers.append(identifier)
    return tuple(dict.fromkeys(identifiers))


def classify_failures(
    failures: tuple[str, ...], baseline: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split failures into what broke and what has not worked yet.

    With no baseline nothing is called a regression. Silence about the past is
    not evidence that nothing broke, and claiming otherwise would put the
    Developer back on the wrong trail with more confidence than before.
    """
    known = set(baseline)
    broken = tuple(name for name in failures if name in known)
    fresh = tuple(name for name in failures if name not in known)
    return broken, fresh


def describe_failures(
    failures: tuple[str, ...],
    baseline: tuple[str, ...],
    diagnostics: dict[str, str] | None = None,
) -> list[str]:
    """What to tell the Developer, most important first.

    A regression leads, because it is the thing it did not mean to do and the
    thing it will not look for on its own.
    """
    broken, fresh = classify_failures(failures, baseline)
    problems: list[str] = []
    if broken:
        problems.append(
            "REGRESSION: these tests passed before this change and now fail — "
            + ", ".join(broken)
            + ". Something the change did broke them; they are not about the new "
            "behaviour."
        )
    if fresh:
        problems.append(
            "The new behaviour is not demonstrated yet by: " + ", ".join(fresh)
        )
    if diagnostics:
        # Dict insertion order is the evidence priority chosen by Reviewer:
        # regressions first, then failures of newly introduced behaviour.
        for identifier, diagnostic in diagnostics.items():
            problems.append(
                f"FAILED ASSERTION (untrusted data) {identifier}:\n{diagnostic}"
            )
        omitted = len(failures) - len(diagnostics)
        if omitted > 0:
            problems.append(
                f"Diagnostics unavailable or omitted for {omitted} additional failures."
            )
    return problems
