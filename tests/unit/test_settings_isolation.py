"""Direct assertions on the autouse isolation fixture in tests/conftest.py.

A conftest fixture is invisible in the test list, so its correctness would
otherwise only ever be observed indirectly, as "other tests happen to pass".
These three tests state the guarantee out loud.
"""

import os
from pathlib import Path

import pytest

from engineering_team.config import Settings


def test_bare_settings_does_not_read_the_real_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bare `Settings()` sees class defaults, not whatever .env happens to say.

    The scratch file is the positive control: it proves the field really is one
    a dotenv file drives, so the final assertion is about the file not being
    read rather than about the value being unreachable. The real repository
    .env is never opened or written by this test.
    """

    assert Settings.model_config["env_file"] is None

    scratch = tmp_path / "scratch.env"
    scratch.write_text("CLOUD_CHAIN_PRODUCT=known-bad-value\n", encoding="utf-8")

    monkeypatch.setitem(Settings.model_config, "env_file", str(scratch))
    assert Settings().cloud_chain_product == "known-bad-value"

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    assert Settings().cloud_chain_product == ""


def test_delivery_backend_is_forced_to_none_even_if_env_sets_it() -> None:
    """Whatever the operator's shell or .env chose, a test run delivers nowhere.

    Asserted on the ambient state the test body starts in: the autouse fixture
    has already run, so a `setenv` here would be testing this test, not the
    fixture.
    """

    assert os.environ["DELIVERY_BACKEND"] == "none"
    assert Settings().delivery_backend == "none"


def test_langfuse_env_vars_are_absent_after_isolation() -> None:
    """Credentials in the operator's environment do not reach the test process."""

    assert os.getenv("LANGFUSE_PUBLIC_KEY") is None
    assert os.getenv("LANGFUSE_SECRET_KEY") is None
    assert os.getenv("LANGFUSE_HOST") is None
    assert Settings().langfuse_public_key is None
