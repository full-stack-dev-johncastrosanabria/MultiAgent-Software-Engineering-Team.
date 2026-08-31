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

# `FAILED path::Class::test - reason` and `path::Class::test PASSED`.
_FAILED = re.compile(r"^\s*FAILED\s+(\S+::\S+)", re.MULTILINE)
_PASSED = re.compile(r"^\s*(\S+::\S+)\s+PASSED", re.MULTILINE)


def failing_tests(output: str) -> tuple[str, ...]:
    """The identifiers pytest reported as failures, in the order printed."""
    return tuple(dict.fromkeys(_FAILED.findall(output or "")))


def passing_tests(output: str) -> tuple[str, ...]:
    """The identifiers pytest reported as passing.

    Needs `-v`, which is why a baseline run asks for it: the compact form prints
    dots and a summary, and a dot names nothing.
    """
    return tuple(dict.fromkeys(_PASSED.findall(output or "")))


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
    failures: tuple[str, ...], baseline: tuple[str, ...]
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
    return problems
