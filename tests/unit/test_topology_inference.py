"""Inferring the services a project needs when it does not declare them (ADR 5).

Every fixture below is a fragment of a real repository's configuration, kept
verbatim so the extraction is measured against what projects actually write --
including Spring's `${VAR:default}` placeholders and .NET's inline connection
strings.
"""

from __future__ import annotations

import pytest

from engineering_team.topology import (
    Dependency,
    derive_compose,
    environment_overrides,
    extract_dependencies,
)

NORTHGATE_TOLL = """spring:
  datasource:
    url: ${NORTHGATE_DB_URL:jdbc:postgresql://localhost:5432/northgate_toll}
    username: ${NORTHGATE_DB_USER:postgres}
    password: ${NORTHGATE_DB_PASSWORD:}
"""
# Verbatim, comment included: this file explains a framework quirk by quoting a
# connection string, and an extractor that reads prose finds a service that does
# not exist.
NORTHGATE_AUDIT = """spring:
  # Boot 4 moved the connection URI to spring.mongodb.*; spring.data.mongodb.uri
  # is silently ignored and falls back to the mongodb://localhost/test default.
  mongodb:
    uri: ${NORTHGATE_MONGO_URI:mongodb://localhost:27017/northgate_audit}
"""
BUSINESSAI = """spring:
  datasource:
    url: jdbc:mysql://localhost:3306/businessai?useSSL=false&serverTimezone=UTC
    username: ${MYSQL_USER:root}
    password: ${MYSQL_PASSWORD:root}
"""
BANKING = """{
  "ConnectionStrings": {
    "Default": "Host=localhost;Port=5432;Database=bankdb;Username=postgres;Password=postgres"
  }
}
"""
INTERVIEW = """{
  "ConnectionStrings": {
    "DefaultConnection": "server=localhost;port=3306;database=InterviewCleanApiDb;user=root;password=s3cr3t;"
  }
}
"""
FLASK = """SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \\
    'sqlite:///flask_api.db'
"""


def test_a_spring_datasource_behind_a_placeholder_is_still_read() -> None:
    """`${VAR:default}` is how these projects write it; the default is the truth."""
    (found,) = extract_dependencies({"application.yaml": NORTHGATE_TOLL})
    assert found.engine == "postgres"
    assert found.port == 5432
    assert found.database == "northgate_toll"
    assert found.user == "postgres"


def test_a_mongo_uri_is_recognised() -> None:
    (found,) = extract_dependencies({"application.yaml": NORTHGATE_AUDIT})
    assert found.engine == "mongo"
    assert found.port == 27017
    assert found.database == "northgate_audit"


def test_query_parameters_do_not_leak_into_the_database_name() -> None:
    (found,) = extract_dependencies({"application.yml": BUSINESSAI})
    assert found.engine == "mysql"
    assert found.database == "businessai"


def test_a_dotnet_connection_string_is_read_inline() -> None:
    (found,) = extract_dependencies({"appsettings.json": BANKING})
    assert found.engine == "postgres"
    assert (found.database, found.user, found.password) == ("bankdb", "postgres", "postgres")


def test_the_other_dotnet_spelling_is_read_too() -> None:
    """`server=`/`user=` rather than `Host=`/`Username=`."""
    (found,) = extract_dependencies({"appsettings.json": INTERVIEW})
    assert found.engine == "mysql"
    assert found.database == "InterviewCleanApiDb"
    assert found.user == "root"


def test_sqlite_needs_no_service_and_that_is_a_result() -> None:
    """A first-class answer, not a failure to infer."""
    assert extract_dependencies({"config.py": FLASK}) == ()


def test_two_components_needing_two_engines_yield_two_services() -> None:
    found = extract_dependencies(
        {"toll/application.yaml": NORTHGATE_TOLL, "audit/application.yaml": NORTHGATE_AUDIT}
    )
    assert {item.engine for item in found} == {"postgres", "mongo"}


def test_the_same_database_named_twice_is_one_service() -> None:
    found = extract_dependencies({"a.yml": BUSINESSAI, "b.yml": BUSINESSAI})
    assert len(found) == 1


def test_extraction_is_deterministic() -> None:
    sources = {"a.yml": BUSINESSAI, "b.yaml": NORTHGATE_TOLL, "c.json": BANKING}
    assert extract_dependencies(sources) == extract_dependencies(dict(reversed(list(sources.items()))))


# -- the two renderings ------------------------------------------------------


def _postgres() -> Dependency:
    (found,) = extract_dependencies({"appsettings.json": BANKING})
    return found


def test_the_run_rendering_publishes_nothing() -> None:
    document = derive_compose((_postgres(),), mode="run")
    assert "ports:" not in document
    assert "internal: true" in document


def test_the_delivery_rendering_publishes_on_localhost() -> None:
    """So a developer runs `docker compose up -d` and their existing config works."""
    document = derive_compose((_postgres(),), mode="delivery")
    assert "5432:5432" in document
    assert "internal: true" not in document


def test_the_delivery_rendering_never_carries_a_password() -> None:
    """A pull request that commits a plaintext credential is a bad pull request."""
    document = derive_compose((_postgres(),), mode="delivery")
    assert "postgres" in document
    assert "${" in document, "credentials should be parameterised"
    assert "Password=postgres" not in document


def test_the_run_rendering_uses_the_projects_own_credentials() -> None:
    """Otherwise the project's own configuration cannot authenticate."""
    document = derive_compose((_postgres(),), mode="run")
    assert "bankdb" in document


def test_every_image_is_pinned_and_the_assumption_is_stated() -> None:
    document = derive_compose((_postgres(),), mode="delivery")
    assert "@sha256:" in document
    assert "assum" in document.lower(), "the version guess must be visible"


def test_an_init_script_is_mounted_when_the_project_ships_one() -> None:
    document = derive_compose(
        (_postgres(),), mode="run", init_script="database/schema.sql"
    )
    assert "/docker-entrypoint-initdb.d/" in document


def test_no_init_mount_when_migrations_run_at_startup() -> None:
    document = derive_compose((_postgres(),), mode="run")
    assert "docker-entrypoint-initdb.d" not in document


# -- redirecting the project off localhost -----------------------------------


def test_spring_is_redirected_by_its_documented_variable() -> None:
    overrides = dict(environment_overrides((_postgres(),), "jvm"))
    assert overrides["SPRING_DATASOURCE_URL"].startswith("jdbc:postgresql://postgres:5432/")
    assert "localhost" not in overrides["SPRING_DATASOURCE_URL"]


def test_dotnet_is_redirected_by_its_double_underscore_binding() -> None:
    overrides = dict(environment_overrides((_postgres(),), "dotnet"))
    assert "ConnectionStrings__Default" in overrides
    assert "Host=postgres" in overrides["ConnectionStrings__Default"]


def test_a_stack_with_no_documented_override_gets_none() -> None:
    """Better to say nothing than to invent a variable the framework ignores."""
    assert environment_overrides((_postgres(),), "node") == ()


def test_a_service_name_is_never_taken_from_the_project() -> None:
    """Names come from the engine, so a hostile config cannot shape the document."""
    document = derive_compose((_postgres(),), mode="run")
    assert "\n  postgres:" in document


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError):
        derive_compose((_postgres(),), mode="whatever")


def test_a_connection_string_inside_a_comment_is_not_a_dependency() -> None:
    """Measured against NorthgateTollPlaza, whose config explains a framework
    quirk by quoting `mongodb://localhost/test` in a comment."""
    found = extract_dependencies({"application.yaml": NORTHGATE_AUDIT})
    assert [item.database for item in found] == ["northgate_audit"]


def test_one_service_per_engine_even_when_several_databases_are_named() -> None:
    """Two databases on one Postgres are one container, not two."""
    two = """url: jdbc:postgresql://localhost:5432/first
url: jdbc:postgresql://localhost:5432/second
"""
    assert len(extract_dependencies({"a.yml": two})) == 1


def test_every_derived_service_declares_readiness() -> None:
    """`--wait` without a healthcheck waits for running, not for ready.

    Measured: a derived Postgres reported up in one second and refused the
    connection that followed.
    """
    for mode in ("run", "delivery"):
        document = derive_compose((_postgres(),), mode=mode)
        assert "healthcheck:" in document
        assert "pg_isready" in document


def test_each_engine_is_probed_the_way_it_answers() -> None:
    from engineering_team.topology import ENGINES

    assert "pg_isready" in ENGINES["postgres"].healthcheck
    assert "mysqladmin" in ENGINES["mysql"].healthcheck
    assert "mongosh" in ENGINES["mongo"].healthcheck


def test_no_probe_can_break_the_document_it_is_written_into() -> None:
    """The probe is emitted inside a double-quoted YAML scalar.

    Measured: a Mongo probe containing double quotes produced a derived file
    compose refused to parse, and the run failed as an infrastructure error for a
    reason that had nothing to do with the project.
    """
    from engineering_team.topology import ENGINES

    for name, engine in ENGINES.items():
        assert '"' not in engine.healthcheck, f"{name} probe would break the YAML"


def test_a_derived_document_is_accepted_by_compose(tmp_path) -> None:
    """The only check that matters: compose itself has to read it."""
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("needs docker")
    from engineering_team.topology import Dependency

    every = tuple(
        Dependency(engine, spec.port, f"{engine}_db", "aset", "aset")
        for engine, spec in __import__(
            "engineering_team.topology", fromlist=["ENGINES"]
        ).ENGINES.items()
    )
    document = tmp_path / "docker-compose.yml"
    document.write_text(derive_compose(every, mode="run"), encoding="utf-8")
    completed = subprocess.run(
        ["docker", "compose", "-f", str(document), "config"],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr[-500:]


# -- .NET connection strings do not name their engine ------------------------


def test_sqlite_in_a_dotnet_connection_string_needs_no_service() -> None:
    """PropFlow writes `Data Source=propflow.db`, which is a file, not a server."""
    found = extract_dependencies(
        {"appsettings.json": '{"ConnectionStrings":{"DefaultConnection":"Data Source=propflow.db"}}'}
    )
    assert found == ()


def test_sql_server_is_not_mistaken_for_mysql() -> None:
    """Both spell the key `Server=`; only the port tells them apart."""
    found = extract_dependencies(
        {"appsettings.json":
         '{"ConnectionStrings":{"Default":"Server=localhost,1433;Database=Shop;User Id=sa;Password=x"}}'}
    )
    assert [item.engine for item in found] == ["mssql"]


def test_mysql_is_still_recognised_by_its_port() -> None:
    found = extract_dependencies(
        {"appsettings.json":
         '{"ConnectionStrings":{"Default":"server=localhost;port=3306;database=D;user=root;password=x"}}'}
    )
    assert [item.engine for item in found] == ["mysql"]


def test_no_engine_carries_a_placeholder_digest() -> None:
    """A digest of zeros looks pinned and resolves to nothing."""
    from engineering_team.topology import ENGINES

    for name, engine in ENGINES.items():
        digest = engine.image.split("@sha256:")[-1]
        assert len(digest) == 64, name
        assert set(digest) != {"0"}, f"{name} carries a placeholder digest"


def test_the_delivery_probe_reads_the_variable_it_parameterised() -> None:
    """Otherwise changing POSTGRES_USER in .env yields a never-healthy service."""
    document = derive_compose((_postgres(),), mode="delivery")
    assert "$$POSTGRES_USER" in document
    assert derive_compose((_postgres(),), mode="run").count("$$") == 0
