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


def test_a_declared_type_is_not_a_credential() -> None:
    """`password: string` is a signature, not a secret.

    The Python path already knew this; the helper that knew it parses Python, so
    the same signature in TypeScript refused the prompt — and once redaction ran,
    it also rewrote the source into `password=[REDACTED] {`, handing the model
    broken code.
    """
    signature = "async fillCredentials(email: string, password: string) {"

    assert redacted_for_cloud(signature) == signature
    require_safe_cloud_context(redacted_for_cloud(signature))


def test_the_marker_is_recognised_where_it_lands_not_only_at_a_line_end() -> None:
    """Redaction that its own checker rejects is worse than no redaction."""
    inline = "{ email: 'a@b.c', password: 'hunter2' },"

    redacted = redacted_for_cloud(inline)

    assert "hunter2" not in redacted
    require_safe_cloud_context(redacted)


def test_documentation_loses_the_value_not_the_emphasis() -> None:
    """`**Password:** `123456`` put markdown where the pattern expected the
    secret, so the asterisks were redacted and the credential survived."""
    documented = "- **Password:** `123456`"

    redacted = redacted_for_cloud(documented)

    assert "123456" not in redacted


def test_a_credential_written_as_prose_is_not_detected() -> None:
    """The honest limit, kept in the suite so it is not rediscovered as a
    surprise. Nothing here matches `key: value`, so nothing is redacted -- and
    since ADR 13 stopped refusing the whole file, this now travels."""
    prose = "- Admin user: `john@test.com` / `123456`"

    assert redacted_for_cloud(prose) == prose
    require_safe_cloud_context(prose)
