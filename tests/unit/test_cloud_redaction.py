"""A project with a database could not use a cloud model at all.

`ServiceStack` reads the connection string out of committed configuration to
start the service, so the password has to be there for the run to work. The
cloud guardrail then refused every prompt that carried that file, and
InterviewCleanApi's Architecture step died on its own appsettings.json. The two
requirements belong to the same system and contradicted each other.
"""

from __future__ import annotations

import json

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


def test_the_marker_survives_an_escaped_payload() -> None:
    """The prompt a role is sent is JSON, so repository text arrives with its
    newlines escaped. `[REDACTED]\\nurl` puts a backslash where the marker's
    exemption expected a line end, so the checker refused the redactor's own
    output -- and every project with a `password:` line in its config died at
    its first Architecture call, before one tool ran."""
    payload = '{"file": "application.yaml", "text": "password: hunter2\\nurl: local"}'

    redacted = redacted_for_cloud(payload)

    assert "hunter2" not in redacted
    require_safe_cloud_context(redacted)


def test_the_marker_is_accepted_when_prose_follows_it() -> None:
    """Redact the whole unquoted value, including prose, before checking it.

    This does not exempt a marker followed by an unredacted credential.
    """
    line = "password: hunter2 as documented in the deployment guide"

    redacted = redacted_for_cloud(line)

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


# spring-demo's own docs, 2026-09-16: Architecture's cloud call was refused after
# redaction and the whole run crashed without a report.
@pytest.mark.parametrize("text", [
    'Then run:\nexport DB_PASSWORD="secret1"\n',
    "docker run -d \\\n  -e MYSQL_ROOT_PASSWORD=secret1 \\\n  mysql:8.0\n",
])
def test_documented_shell_credentials_are_redacted_so_the_check_passes(text):
    redacted = redacted_for_cloud(text)
    assert "secret1" not in redacted
    require_safe_cloud_context(redacted)
    require_safe_cloud_context("Repository data: " + json.dumps({"content": redacted}))


def test_a_value_after_a_continuation_marker_is_still_refused():
    with pytest.raises(ValueError):
        require_safe_cloud_context("password=[REDACTED] \\ secret2")


def test_a_refused_cloud_context_is_a_run_error_not_a_crash(monkeypatch):
    import httpx

    from engineering_team.config import Settings
    from engineering_team.contracts.enums import AgentRole
    from engineering_team.llm import cloud
    from engineering_team.llm.cloud import CloudModelRuntime
    from tests.unit.test_cloud_runtime import cloud_envelope, product_candidate

    def refuse(_):
        raise ValueError("sensitive content is not allowed in cloud context")

    monkeypatch.setattr(cloud, "require_safe_cloud_context", refuse)
    settings = Settings(_env_file=None, cloud_enabled=True, mistral_api_key="fixture",
                        cloud_chain_product="mistral:mistral-small-latest")
    transport = httpx.MockTransport(lambda _: pytest.fail("prompt was sent"))
    with httpx.Client(transport=transport) as client, pytest.raises(
        RuntimeError, match="CLOUD_FALLBACK_UNAVAILABLE: sensitive content"
    ):
        CloudModelRuntime(settings, client=client, primary=True).invoke_artifact(
            AgentRole.PRODUCT, cloud_envelope(), product_candidate())
