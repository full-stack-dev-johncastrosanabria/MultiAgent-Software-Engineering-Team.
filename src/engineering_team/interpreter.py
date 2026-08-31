"""Which Python a project needs, and why an install failed without one.

The ephemeral environment is built from the operator's interpreter. That is fine
until a project pins dependencies older than it: `pandas==2.1.4` publishes wheels
for cp39 through cp312, so on a 3.14 host pip falls back to building it from
source, ninja stops, and the run reports "security validation tool did not pass".
The words "Python version" appear nowhere.

Two of the three real Python projects this was measured against declare nothing
about the interpreter they need. So reading declarations is necessary and not
sufficient: the failure has to become legible even when there is nothing to read.
"""

from __future__ import annotations

import re

# `requires-python = ">=3.10"` in pyproject, `python_requires=">=3.9"` in setup.
_DECLARED = re.compile(
    r"""(?:requires[-_]python|python_requires)\s*[=:]\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
# `FROM python:3.11-slim`, the only statement of intent some projects make.
_DOCKER_PYTHON = re.compile(
    r"^\s*FROM\s+(?:[\w.-]+/)?python:(\d+)\.(\d+)", re.IGNORECASE | re.MULTILINE
)
_VERSION_FILE = re.compile(r"^\s*(\d+)\.(\d+)")
_SPECIFIER = re.compile(r"(==|>=|<=|!=|~=|>|<)\s*(\d+)(?:\.(\d+))?(?:\.\*)?")
# The shape of a build that had no wheel to install.
_SOURCE_BUILD = re.compile(
    r"(?i)(compiling cython|ninja: build stopped|metadata-generation-failed"
    r"|building wheel for|error: command .*(gcc|clang|cc1))"
)
_PIN = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([0-9][\w.]*)", re.MULTILINE)
# Where pip says which package it is building. Naming the first pin instead sent
# the operator after Flask, which is pure Python and never builds.
_BUILDING = re.compile(
    r"(?i)(?:building wheels? for(?: collected packages:)?|preparing metadata for"
    r"|error: (?:sub)?process .*?for)\s+([A-Za-z0-9._-]+)"
)


def python_requirement(sources: dict[str, str]) -> str | None:
    """The interpreter range a project declares, or None when it declares none.

    None is an answer, not a failure. Most applications say nothing, and treating
    silence as a range would invent a constraint the project never stated.
    """
    for name in sorted(sources):
        lowered = name.lower()
        text = sources[name]
        if lowered.endswith(("pyproject.toml", "setup.py", "setup.cfg")):
            match = _DECLARED.search(text)
            if match:
                return match.group(1).strip()
        if lowered.endswith(".python-version"):
            match = _VERSION_FILE.search(text)
            if match:
                return f"=={match.group(1)}.{match.group(2)}.*"
    # Last: a Dockerfile is a weaker statement than a declaration, but for a
    # project that declares nothing it is the version it actually runs on.
    for name in sorted(sources):
        if name.lower().endswith("dockerfile"):
            match = _DOCKER_PYTHON.search(sources[name])
            if match:
                return f"=={match.group(1)}.{match.group(2)}.*"
    return None


def satisfies(requirement: str | None, version: tuple[int, int]) -> bool:
    """Whether an interpreter version meets a declared range.

    Deliberately small: enough for the comparisons projects actually write, and
    it does not pretend to be a full specifier implementation.
    """
    if not requirement:
        return True
    major, minor = version
    for operator, raw_major, raw_minor in _SPECIFIER.findall(requirement):
        bound = (int(raw_major), int(raw_minor) if raw_minor else 0)
        current = (major, minor if raw_minor else 0)
        if operator == "==" and current != bound:
            return False
        if operator == "!=" and current == bound:
            return False
        if operator == ">=" and current < bound:
            return False
        if operator == "<=" and current > bound:
            return False
        if operator == ">" and current <= bound:
            return False
        if operator == "<" and current >= bound:
            return False
        if operator == "~=" and (major != bound[0] or minor < bound[1]):
            return False
    return True


def describe_install_failure(
    output: str,
    *,
    interpreter: tuple[int, int],
    requirement: str | None,
    pins: tuple[str, ...],
) -> str | None:
    """Say that an install failed over the interpreter, when it did.

    Returns None when the evidence does not point that way. Guessing would be
    worse than saying nothing: an operator who is told the wrong cause looks in
    the wrong place, which is the whole complaint behind findings 7, 9 and 10.
    """
    version = f"{interpreter[0]}.{interpreter[1]}"
    if requirement and not satisfies(requirement, interpreter):
        return (
            f"this project declares Python {requirement} and the environment was "
            f"built with {version}. Nothing was installed; the interpreter has to "
            "match before the dependencies can."
        )
    if not _SOURCE_BUILD.search(output or ""):
        return None
    # Name only what the output actually blamed. A pin that never appears in the
    # failure is not evidence, and naming it is the misleading headline these
    # findings are about.
    named = {match.casefold() for match in _BUILDING.findall(output or "")}
    culprits = [
        pin for pin in pins if pin.split("==")[0].casefold() in named
    ]
    if culprits:
        subject = f"{', '.join(culprits[:3])} publish"
        if len(culprits) == 1:
            subject = f"{culprits[0]} publishes"
    else:
        subject = "one of its pinned dependencies publishes"
    return (
        f"a dependency was built from source instead of installed from a wheel, "
        f"and the build failed. The environment uses Python {version}; {subject} "
        "no wheel for it, so pip fell back to compiling. This is an interpreter "
        "mismatch, not a defect in the project's code."
    )


def pinned_requirements(text: str) -> tuple[str, ...]:
    """The exact pins a requirements file declares, in the order written."""
    return tuple(f"{name}=={version}" for name, version in _PIN.findall(text))
