"""Choosing the interpreter a project can actually be built with.

Two of three real Python projects declare nothing, so the constraint has to come
from what their pins publish. FlaskApiProduct pins pandas==2.1.4 and
numpy==1.26.2, which stop at cp312, while the environment was built with 3.14 —
pip compiled from source and the run died on ninja.

The wheel tags answer it, but only read correctly: an abi3 wheel tagged cp37
works on 3.7 *and everything after*, so intersecting it as an exact version would
conclude a project needs Python 3.7.
"""

from __future__ import annotations

import pytest

from engineering_team.interpreter import (
    PYTHON_IMAGES,
    highest_supported,
    python_image,
    wheel_python_versions,
)

PANDAS = [
    "pandas-2.1.4-cp39-cp39-macosx_11_0_arm64.whl",
    "pandas-2.1.4-cp312-cp312-macosx_11_0_arm64.whl",
    "pandas-2.1.4.tar.gz",
]
FLASK = ["flask-3.0.0-py3-none-any.whl"]
CRYPTOGRAPHY = ["cryptography-41.0.7-cp37-abi3-macosx_10_12_universal2.whl"]


def test_an_exact_tag_names_exactly_that_version() -> None:
    assert (3, 12) in wheel_python_versions(PANDAS)
    assert (3, 14) not in wheel_python_versions(PANDAS)


def test_a_universal_wheel_constrains_nothing() -> None:
    """Flask is pure Python; blaming it for an interpreter problem was the bug."""
    assert wheel_python_versions(FLASK) is None


def test_an_abi3_wheel_is_a_floor_and_not_a_ceiling() -> None:
    """cp37-abi3 runs on 3.7 and everything after. Reading it as an exact
    version would conclude the project needs Python 3.7."""
    versions = wheel_python_versions(CRYPTOGRAPHY)
    assert (3, 12) in versions
    assert (3, 14) in versions
    assert (3, 6) not in versions


def test_the_highest_version_every_pin_supports_is_chosen() -> None:
    """FlaskApiProduct, exactly: pandas and numpy stop at 3.12, Flask is
    universal, cryptography is abi3 from 3.7."""
    assert highest_supported({
        "pandas==2.1.4": PANDAS,
        "flask==3.0.0": FLASK,
        "cryptography==41.0.7": CRYPTOGRAPHY,
    }) == (3, 12)


def test_a_project_of_universal_wheels_is_unconstrained() -> None:
    assert highest_supported({"flask==3.0.0": FLASK}) is None


def test_no_common_version_is_reported_rather_than_guessed() -> None:
    """Two pins that cannot share an interpreter is a real answer."""
    impossible = {
        "old==1": ["old-1-cp38-cp38-any.whl"],
        "new==2": ["new-2-cp313-cp313-any.whl"],
    }
    assert highest_supported(impossible) is None


# -- the image that carries it ----------------------------------------------


def test_every_offered_interpreter_has_a_pinned_image() -> None:
    for version, image in PYTHON_IMAGES.items():
        assert "@sha256:" in image, version
        assert len(image.split("@sha256:")[1]) == 64


def test_the_image_matches_the_version_the_project_needs() -> None:
    assert "3.12" in python_image((3, 12)) or python_image((3, 12)) == PYTHON_IMAGES[(3, 12)]
    assert python_image((3, 12)) != python_image((3, 13))


def test_an_unavailable_interpreter_is_refused_rather_than_approximated() -> None:
    """Silently running 3.13 for a project that needs 3.9 reproduces the bug."""
    with pytest.raises(KeyError):
        python_image((3, 9))


# -- putting it together for a project ---------------------------------------


def _fake_index(published: dict[str, list[str]]):
    def fetch(name: str, version: str) -> list[str]:
        return published.get(f"{name}=={version}", [])
    return fetch


def test_a_declared_requirement_wins_over_the_pins(tmp_path) -> None:
    """A project that states its interpreter is not second-guessed."""
    from engineering_team.interpreter import select_interpreter

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.11,<3.12"\n', encoding="utf-8"
    )
    (tmp_path / "requirements.txt").write_text("pandas==2.1.4\n", encoding="utf-8")
    assert select_interpreter(tmp_path, fetch=_fake_index({})) == (3, 11)


def test_the_pins_decide_when_nothing_is_declared(tmp_path) -> None:
    """FlaskApiProduct: no declaration anywhere, and the answer is 3.12."""
    from engineering_team.interpreter import select_interpreter

    (tmp_path / "requirements.txt").write_text(
        "Flask==3.0.0\npandas==2.1.4\n", encoding="utf-8"
    )
    fetch = _fake_index({
        "Flask==3.0.0": FLASK,
        "pandas==2.1.4": PANDAS,
    })
    assert select_interpreter(tmp_path, fetch=fetch) == (3, 12)


def test_a_project_with_no_constraint_at_all_gets_none(tmp_path) -> None:
    """Nothing to derive is not a failure; the default interpreter stands."""
    from engineering_team.interpreter import select_interpreter

    (tmp_path / "requirements.txt").write_text("Flask==3.0.0\n", encoding="utf-8")
    assert select_interpreter(tmp_path, fetch=_fake_index({"Flask==3.0.0": FLASK})) is None


def test_an_index_that_cannot_be_reached_does_not_invent_a_version(tmp_path) -> None:
    """Guessing offline would put a project on the wrong interpreter silently."""
    from engineering_team.interpreter import select_interpreter

    def unreachable(name: str, version: str) -> list[str]:
        raise OSError("no network")

    (tmp_path / "requirements.txt").write_text("pandas==2.1.4\n", encoding="utf-8")
    assert select_interpreter(tmp_path, fetch=unreachable) is None
