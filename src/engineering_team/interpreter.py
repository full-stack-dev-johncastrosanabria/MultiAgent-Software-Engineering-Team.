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


# Interpreters the container runner can provide, pinned by digest. A project that
# needs one outside this set is refused rather than approximated: running 3.13 for
# a project that needs 3.9 reproduces exactly the failure this exists to prevent.
PYTHON_IMAGES: dict[tuple[int, int], str] = {
    (3, 11): (
        "python@sha256:"
        "1042b61448fef4ba92d16a8c7eb4996d027568ce64792a7877fd88511e0af7c6"
    ),
    (3, 12): (
        "python@sha256:"
        "09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217"
    ),
    (3, 13): (
        "python@sha256:"
        "7ce4b6dfe35e55397b7cda544f8a13f191b7ae28dc5aad71fe664dbc9bc2623f"
    ),
}

_EXACT_TAG = re.compile(r"-cp(\d)(\d+)-cp\d+")
_ABI3_TAG = re.compile(r"-cp(\d)(\d+)-abi3")
_UNIVERSAL = re.compile(r"-py3-none-any\.whl$|-py2\.py3-none-any\.whl$")
# The range worth considering. Below it nothing here can run; above it is the
# future, and claiming support for versions that do not exist helps nobody.
_CONSIDERED = tuple((3, minor) for minor in range(8, 16))


def wheel_python_versions(filenames: list[str]) -> set[tuple[int, int]] | None:
    """Which interpreters a released package publishes wheels for.

    None means it constrains nothing: a pure-Python wheel runs anywhere, and
    treating it as a constraint is what made the first diagnosis blame Flask.

    An `abi3` wheel is a floor, not a point. `cp37-abi3` runs on 3.7 and every
    version after it, so reading the tag as an exact version would conclude that
    a project needs Python 3.7.
    """
    versions: set[tuple[int, int]] = set()
    saw_wheel = False
    for name in filenames:
        if not name.endswith(".whl"):
            continue
        saw_wheel = True
        if _UNIVERSAL.search(name):
            return None
        floor = _ABI3_TAG.search(name)
        if floor:
            bound = (int(floor.group(1)), int(floor.group(2)))
            versions |= {v for v in _CONSIDERED if v >= bound}
            continue
        exact = _EXACT_TAG.search(name)
        if exact:
            versions.add((int(exact.group(1)), int(exact.group(2))))
    return versions if saw_wheel and versions else None


def highest_supported(
    published: dict[str, list[str]],
) -> tuple[int, int] | None:
    """The newest interpreter every pinned dependency can be installed on.

    None when nothing constrains the choice, and also when the pins cannot share
    an interpreter at all -- a real answer, and not one to paper over by picking
    something that satisfies most of them.
    """
    common: set[tuple[int, int]] | None = None
    for filenames in published.values():
        versions = wheel_python_versions(filenames)
        if versions is None:
            continue
        common = versions if common is None else (common & versions)
    if not common:
        return None
    return max(common)


def python_image(version: tuple[int, int]) -> str:
    """The pinned image carrying one interpreter, or a refusal."""
    try:
        return PYTHON_IMAGES[version]
    except KeyError:
        offered = ", ".join(f"{a}.{b}" for a, b in sorted(PYTHON_IMAGES))
        raise KeyError(
            f"no image for Python {version[0]}.{version[1]}; offered: {offered}"
        ) from None


def _declared_version(requirement: str) -> tuple[int, int] | None:
    """The single interpreter a declared range actually admits, if only one does."""
    admitted = [v for v in _CONSIDERED if satisfies(requirement, v)]
    return max(admitted) if admitted else None


def select_interpreter(
    root, *, fetch=None
) -> tuple[int, int] | None:
    """Which Python this project should be built with.

    A declaration wins: a project that states its interpreter is not
    second-guessed. Where none exists -- two of the three real projects measured
    -- the pins decide, because what a released version publishes wheels for is
    the fact that determines whether pip installs or compiles.

    None means nothing constrains the choice, including when the index cannot be
    reached. Guessing offline would put a project on the wrong interpreter
    silently, which is the failure this exists to prevent.
    """
    from pathlib import Path

    root = Path(root)
    sources = {}
    for name in (
        "pyproject.toml", "setup.py", "setup.cfg", ".python-version",
        "Dockerfile", "backend/Dockerfile",
    ):
        candidate = root / name
        if candidate.is_file():
            try:
                sources[name] = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    declared = python_requirement(sources)
    if declared:
        return _declared_version(declared)

    requirements = root / "requirements.txt"
    if not requirements.is_file():
        return None
    try:
        pins = pinned_requirements(
            requirements.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return None
    if fetch is None:
        fetch = _pypi_files
    published: dict[str, list[str]] = {}
    for pin in pins:
        name, version = pin.split("==", 1)
        try:
            published[pin] = fetch(name, version)
        except (OSError, ValueError):
            return None
    return highest_supported(published)


def _pypi_files(name: str, version: str) -> list[str]:
    """The files an index published for one released version."""
    import json
    import urllib.request

    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        return [item["filename"] for item in json.load(response)["urls"]]
