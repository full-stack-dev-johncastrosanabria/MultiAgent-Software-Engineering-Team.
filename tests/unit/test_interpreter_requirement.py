"""A project's interpreter is the project's, not the operator's (finding 11).

FlaskApiProduct pins `pandas==2.1.4`, which publishes wheels for cp39 through
cp312. The environment was built from the operator's 3.14.7, pip fell back to
building pandas from source, ninja stopped, and the run reported "security
validation tool did not pass". Nothing anywhere said the words "Python version".

Two projects out of three declare nothing about the interpreter they need, so
reading declarations is necessary and not sufficient: the failure has to become
legible even when there is nothing to read.
"""

from __future__ import annotations

from engineering_team.interpreter import (
    describe_install_failure,
    python_requirement,
    satisfies,
)

PYPROJECT = '[project]\nname = "x"\nrequires-python = ">=3.10,<3.13"\n'
SETUP_PY = 'setup(name="x", python_requires=">=3.9")\n'
DOCKERFILE = "FROM python:3.11-slim\nWORKDIR /app\n"


def test_a_declared_requirement_is_read_from_pyproject() -> None:
    assert python_requirement({"pyproject.toml": PYPROJECT}) == ">=3.10,<3.13"


def test_a_pinned_version_file_is_read() -> None:
    assert python_requirement({".python-version": "3.11.9\n"}) == "==3.11.*"


def test_a_dockerfile_states_the_interpreter_the_project_runs_on() -> None:
    """NeoNova declares nothing else, and this is what it ships with."""
    assert python_requirement({"backend/Dockerfile": DOCKERFILE}) == "==3.11.*"


def test_setup_py_is_read_when_that_is_all_there_is() -> None:
    assert python_requirement({"setup.py": SETUP_PY}) == ">=3.9"


def test_a_project_that_declares_nothing_says_so() -> None:
    """FlaskApiProduct. Silence is a distinct answer from a range."""
    assert python_requirement({"requirements.txt": "flask==3.0.0\n"}) is None


def test_the_declaration_is_checked_against_a_real_version() -> None:
    assert satisfies(">=3.10,<3.13", (3, 11)) is True
    assert satisfies(">=3.10,<3.13", (3, 14)) is False
    assert satisfies("==3.11.*", (3, 11)) is True
    assert satisfies("==3.11.*", (3, 12)) is False
    assert satisfies(None, (3, 14)) is True, "nothing declared constrains nothing"


# -- making the failure legible ----------------------------------------------


NINJA_WALL = """
Building wheels for collected packages: pandas
  [42/151] Compiling Cython source .../pandas_d6b57c9d
  ninja: build stopped: subcommand failed.
  error: metadata-generation-failed
"""


def test_a_source_build_failure_names_the_interpreter() -> None:
    """The operator sees a compiler error; what they need is the version."""
    message = describe_install_failure(
        NINJA_WALL, interpreter=(3, 14), requirement=None,
        pins=("pandas==2.1.4", "numpy==1.26.2"),
    )
    assert "3.14" in message
    assert "pandas==2.1.4" in message
    assert "wheel" in message.lower()


def test_it_names_the_package_that_failed_and_not_the_first_one_listed() -> None:
    """Measured on the real project: the message blamed Flask==3.0.0, which is
    pure Python and has a universal wheel. The failing package was pandas, and
    naming the wrong one is the misleading headline these findings are about."""
    message = describe_install_failure(
        NINJA_WALL, interpreter=(3, 14), requirement=None,
        pins=("Flask==3.0.0", "flask-cors==4.0.0", "pandas==2.1.4"),
    )
    assert "pandas==2.1.4" in message
    assert "Flask==3.0.0" not in message


def test_it_says_nothing_specific_when_the_output_names_nothing() -> None:
    """Better a general statement than a confident wrong one."""
    message = describe_install_failure(
        "error: command 'clang' failed\n", interpreter=(3, 14),
        requirement=None, pins=("Flask==3.0.0", "pandas==2.1.4"),
    )
    assert "Flask==3.0.0" not in message
    assert "pinned" in message.lower()


def test_a_declared_mismatch_is_named_before_anything_is_attempted() -> None:
    message = describe_install_failure(
        "", interpreter=(3, 14), requirement=">=3.10,<3.13", pins=(),
    )
    assert ">=3.10,<3.13" in message
    assert "3.14" in message


def test_an_ordinary_install_failure_is_left_alone() -> None:
    """Not every failure is about the interpreter, and guessing would mislead."""
    assert describe_install_failure(
        "ERROR: Could not find a version that satisfies the requirement nope",
        interpreter=(3, 12), requirement=None, pins=("nope==1.0",),
    ) is None
