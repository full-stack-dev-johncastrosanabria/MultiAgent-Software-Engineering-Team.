"""A project with a database could not use a cloud model at all.

`ServiceStack` reads the connection string out of committed configuration to
start the service, so the password has to be there for the run to work. The
cloud guardrail then refused every prompt that carried that file, and
InterviewCleanApi's Architecture step died on its own appsettings.json. The two
requirements belong to the same system and contradicted each other.
"""

from __future__ import annotations

import pytest

from engineering_team.guardrails.secrets import (
    redacted_for_cloud,
    require_safe_cloud_context,
)

_CONFIG = (
    '{"ConnectionStrings": {"DefaultConnection": '
    '"server=localhost;port=3306;database=Db;user=root;password=Cnzmws67;"}}'
)


def test_a_configuration_file_travels_without_its_password() -> None:
    redacted = redacted_for_cloud(_CONFIG)

    assert "Cnzmws67" not in redacted
    assert "REDACTED" in redacted
    assert "server=localhost" in redacted


def test_what_redaction_leaves_still_has_to_pass_the_original_check() -> None:
    """The order is the safety argument.

    Redacting and then checking cannot send anything the check would have
    stopped: a value the detector matches is replaced, and one it does not match
    was already travelling before this existed.
    """
    require_safe_cloud_context(redacted_for_cloud(_CONFIG))

    with pytest.raises(ValueError):
        require_safe_cloud_context(_CONFIG)


def test_redaction_reaches_inside_the_structures_a_prompt_is_built_from() -> None:
    payload = {
        "evidence": [{"chunk": _CONFIG}],
        "files": ("appsettings.json", _CONFIG),
        "depth": 3,
    }

    redacted = redacted_for_cloud(payload)

    assert "Cnzmws67" not in str(redacted)
    assert redacted["depth"] == 3
    assert redacted["files"][0] == "appsettings.json"


def test_a_mapping_keyed_by_a_secret_is_still_refused() -> None:
    """Not a document that quotes a password -- a structure whose purpose is to
    carry one. Redacting it would leave nothing worth sending."""
    with pytest.raises(ValueError):
        redacted_for_cloud({"password": "Cnzmws67"})


def test_presenting_a_credential_file_is_still_refused() -> None:
    with pytest.raises(ValueError):
        redacted_for_cloud({"file": ".env", "content": "TOKEN=abc"})


def test_content_the_detector_does_not_match_is_left_alone() -> None:
    """Stated so the limit is on the record: this changes what happens to
    secrets that are found, not how many are found."""
    prose = "The service reads its configuration from the environment."

    assert redacted_for_cloud(prose) == prose
