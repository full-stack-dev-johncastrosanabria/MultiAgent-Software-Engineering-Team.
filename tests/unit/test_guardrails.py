import json

import pytest

from engineering_team.contracts.enums import RouteTarget
from engineering_team.guardrails.routes import validate_route
from engineering_team.guardrails.secrets import (
    redact_secrets,
    redacted_document,
    require_safe_cloud_context,
)
from engineering_team.guardrails.validation import require_explicit_destructive_authorization


def test_secret_redactor_removes_known_secret_values() -> None:
    assert "secret-value" not in redact_secrets("token=secret-value", {"secret-value"})


@pytest.mark.parametrize("source", [
    "spring:\n  datasource:\n    password: database-credential\n    username: orders\n",
    "environment:\n  POSTGRES_PASSWORD: database-credential\n  POSTGRES_DB: orders\n",
    'password = "database credential with spaces"\n',
    "password: '[REDACTED]'\n",
    'password: "[REDACTED]"\n',
])
def test_cloud_guard_accepts_completely_redacted_repository_evidence(source):
    redacted = redact_secrets(source)
    assert "database-credential" not in redacted
    assert "database credential with spaces" not in redacted
    require_safe_cloud_context(redacted)
    require_safe_cloud_context("Repository data: " + json.dumps({"content": redacted}))


@pytest.mark.parametrize("source", [
    "password=[REDACTED]suffix",
    "password=prefix[REDACTED]",
    'password="[REDACTED]suffix"',
    "password=[REDACTED]\nsecret=real-value",
    "password=[REDACTED], api_key=real-value",
    "password=[REDACTED] credential with spaces",
    "password=[REDACTED] \tcredential with spaces",
])
def test_redaction_marker_does_not_hide_remaining_credentials(source):
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context(source)
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context("Repository data: " + json.dumps({"content": source}))


@pytest.mark.parametrize("source", [
    "password=multiword credential with spaces\nusername=orders\n",
    "spring:\n  datasource:\n    password: multiword credential with spaces\n    username: orders\n",
    "  POSTGRES_PASSWORD: multiword credential, with; punctuation\n  POSTGRES_USER: orders\n",
])
def test_redactor_removes_complete_unquoted_line_values(source):
    redacted = redact_secrets(source)
    for fragment in ("multiword", "credential", "spaces", "punctuation"):
        assert fragment not in redacted
    assert "orders" in redacted
    require_safe_cloud_context(redacted)
    require_safe_cloud_context("Repository data: " + json.dumps({"content": redacted}))


def test_cloud_context_rejects_secondary_gemini_credential_name() -> None:
    with pytest.raises(ValueError, match="sensitive content"):
        require_safe_cloud_context({"gemini_api_key_2": "secondary-secret"})


@pytest.mark.parametrize("assignment", [
    "GEMINI_API_KEY_2=fake-secondary-credential",
    "gemini_api_key_2: 'fake-secondary-credential'",
    'GEMINI_API_KEY_2="fake-secondary-credential"',
])
def test_secondary_credential_assignment_is_redacted_and_blocked(assignment):
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context(assignment)
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context("Context: " + json.dumps({"content": assignment}))
    redacted = redact_secrets(assignment)
    assert "fake-secondary-credential" not in redacted
    require_safe_cloud_context(redacted)


def test_delivery_refuses_secondary_credential_assignment():
    from engineering_team.delivery import DeliveryRefused, GitDelivery, Proposal

    proposal = Proposal(
        run_id="secondary-key-test", branch="aset/secondary-key-test",
        title="Test proposal", body="GEMINI_API_KEY_2=fake-secondary-credential",
        files={},
    )
    with pytest.raises(DeliveryRefused, match="secret"):
        GitDelivery._check_no_secret(proposal)


def test_cloud_context_rejects_env_content() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context({"file": ".env", "content": "KEY=value"})


@pytest.mark.parametrize("key", ["mistral_api_key", "open_router_api_key", "openrouter_api_key"])
def test_cloud_context_rejects_new_provider_credentials(key):
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context({key: "credential-value"})


@pytest.mark.parametrize("source", [
    "def login(password: str):\n    return verify(password)\n",
    "def contraseña(password: str):\n    return verify(password)\n",
    "class Login:\n    password: str = Field(min_length=1, max_length=256)\n",
])
def test_cloud_guard_accepts_type_declarations_without_credentials(source):
    require_safe_cloud_context(source)
    require_safe_cloud_context("ContextEnvelope: " + json.dumps({"content": source}))
    require_safe_cloud_context("Repository data:\n```python\n" + source + "\n```")


@pytest.mark.parametrize("source", [
    'password = "real-value"',
    'def login(password: str = "real-value"):\n    pass',
    'class Login:\n    password: str = "real-value"',
    'class Login:\n    password: str = Field(default="real-value")',
    'class Login:\n    password: str = Field(\n        # secret=real-value\n        min_length=1\n    )',
    'class Login:\n    password: (\n        # secret=real-value\n        str\n    )',
    'def login(password: str):\n    # secret=real-value\n    pass',
    'def contraseña(password: str):\n    secret="real-value"\n    return password',
])
def test_cloud_guard_still_rejects_secrets_in_typed_python(source):
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context(source)
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context("ContextEnvelope: " + json.dumps({"content": source}))
    with pytest.raises(ValueError, match="sensitive"):
        require_safe_cloud_context("Repository data:\n```python\n" + source + "\n```")


def test_route_validator_rejects_disallowed_target() -> None:
    with pytest.raises(ValueError):
        validate_route(RouteTarget.ARCHITECTURE, {RouteTarget.DEVELOPER})


def test_destructive_operations_require_explicit_authorization() -> None:
    with pytest.raises(PermissionError):
        require_explicit_destructive_authorization(False)


def test_documented_password_parameter_is_not_treated_as_a_secret() -> None:
    """A Google-style Args entry documents an argument; it carries no value.

    The agents write these routinely, and blocking them stopped legitimate runs on
    a docstring line that contained no credential at all.
    """
    require_safe_cloud_context(
        'def restablecer(token, nueva_password):\n'
        '    """Restablece la contraseña.\n\n'
        '    Args:\n'
        '        nueva_password: Nueva contraseña para el usuario.\n'
        '    """\n'
    )


@pytest.mark.parametrize(
    "docstring_value",
    [
        "password: hunter2",
        "api_key: aB3xQ9tZ7LmW2pR4vN8sK1",
        "password: la clave es aB3xQ9tZ7LmW2pR4vN8",
    ],
)
def test_a_real_credential_inside_a_docstring_is_still_blocked(docstring_value: str) -> None:
    """The prose exemption must not become a way to smuggle a value out.

    A bare token has no whitespace, and a credential-shaped run is rejected even when
    it is surrounded by prose.
    """
    with pytest.raises(ValueError, match="sensitive content"):
        require_safe_cloud_context(f'def f():\n    """Doc.\n\n    Args:\n        {docstring_value}\n    """\n')


def test_redacting_the_leaves_keeps_the_document_valid_json() -> None:
    """El bug concreto que `redacted_document` cierra.

    `redact_secrets(json.dumps(...))` redacta el documento *codificado*, donde la
    comilla de cierre del valor forma parte de la línea que el patrón orientado a
    líneas reemplaza: `"KEY=change-me",` quedaba como `"KEY=[REDACTED]` y el
    archivo de evidencia dejaba de parsear mientras se seguía escribiendo. Este
    test fija las dos mitades: el orden equivocado rompe el JSON, el correcto no.
    """
    report = {"environment": ["POSTGRES_PASSWORD=change-me"]}

    broken = redact_secrets(json.dumps(report, indent=2))
    assert "change-me" not in broken
    with pytest.raises(ValueError):
        json.loads(broken)

    encoded = json.dumps(redacted_document(report), indent=2)
    assert "change-me" not in encoded
    assert json.loads(encoded) == {"environment": ["POSTGRES_PASSWORD=[REDACTED]"]}


def test_redacted_document_descends_through_dicts_lists_and_tuples() -> None:
    """La evidencia de un benchmark es un árbol, no una cadena.

    Los tres contenedores que los runners producen se recorren, y los escalares
    que no son cadenas se devuelven tal cual: un `returncode` que llegara como
    `"3"` haría ilegible el informe.
    """
    document = {
        "components": [
            {
                "env": ("MYSQL_ROOT_PASSWORD=change-me", "MYSQL_DB=orders"),
                "result": {"status": "passed", "returncode": 0, "failed": None},
            }
        ],
        "finished": True,
    }

    redacted = redacted_document(document)

    leaf = redacted["components"][0]
    assert leaf["env"] == ("MYSQL_ROOT_PASSWORD=[REDACTED]", "MYSQL_DB=orders")
    # Los contenedores conservan su tipo: la función redacta, no normaliza.
    assert isinstance(leaf["env"], tuple)
    assert leaf["result"] == {"status": "passed", "returncode": 0, "failed": None}
    assert redacted["finished"] is True
    # Y sigue siendo serializable, que es para lo único que existe.
    assert json.loads(json.dumps(redacted))["components"][0]["env"] == [
        "MYSQL_ROOT_PASSWORD=[REDACTED]", "MYSQL_DB=orders",
    ]


def test_redacted_document_leaves_the_keys_alone() -> None:
    """Decisión deliberada, documentada en la propia función.

    Un mapa indexado por una credencial es otro problema, y quien lo rechaza es
    `require_safe_cloud_context`. Redactar claves aquí cambiaría la forma del
    documento sin que nadie lo pidiera.
    """
    redacted = redacted_document({"password=hunter2": "password=hunter2"})

    assert list(redacted) == ["password=hunter2"]
    assert redacted["password=hunter2"] == "password=[REDACTED]"
