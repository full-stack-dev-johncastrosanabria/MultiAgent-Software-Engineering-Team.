"""The topology a project declares, and the override that makes it safe (ADR 5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_team.services import (
    ServiceTopology,
    classify_services,
    find_compose_file,
    override_document,
)

# Shaped after PruebaNuevosIngresosBackend, the one repository of six that
# declares its own topology: Postgres and Kafka as infrastructure, an init
# container, and three services built from the repository's own Dockerfiles.
MODEL = {
    "services": {
        "postgres": {"image": "postgres:17-alpine", "ports": [{"published": "5432"}],
                     "healthcheck": {"test": ["CMD-SHELL", "pg_isready"]}},
        "kafka": {"image": "apache/kafka:4.3.1", "ports": [{"published": "9092"}],
                  "healthcheck": {"test": ["CMD-SHELL", "true"]}},
        "kafka-init": {"image": "apache/kafka:4.3.1"},
        "order-ms": {"image": "order-ms:1.0.0", "build": {"context": "./order-ms"}},
        "payment-ms": {"image": "payment-ms:1.0.0", "build": {"context": "./payment-ms"}},
        "frontend": {"image": "frontend:1.0.0", "build": {"context": "./frontend"}},
    }
}


def test_services_built_from_the_repository_are_not_infrastructure() -> None:
    """Starting them means executing Dockerfiles we did not write."""
    topology = classify_services(MODEL)
    assert topology.infrastructure == ("kafka", "kafka-init", "postgres")
    assert topology.application == ("frontend", "order-ms", "payment-ms")


def test_an_image_only_service_is_infrastructure_even_without_a_healthcheck() -> None:
    """kafka-init is a one-shot; it still is not the project's own code."""
    topology = classify_services(MODEL)
    assert "kafka-init" in topology.infrastructure


def test_a_compose_without_services_yields_nothing_rather_than_failing() -> None:
    assert classify_services({}) == ServiceTopology((), ())


def test_compose_is_found_by_the_names_compose_itself_accepts(tmp_path: Path) -> None:
    assert find_compose_file(tmp_path) is None
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    assert find_compose_file(tmp_path).name == "docker-compose.yml"


def test_the_canonical_name_wins_over_the_legacy_one(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    assert find_compose_file(tmp_path).name == "compose.yaml"


def test_the_override_closes_the_network_and_the_ports() -> None:
    """Both are required: a project's database must not reach out or be reached."""
    document = override_document(("postgres", "kafka"))
    assert "internal: true" in document
    assert document.count("ports: !override []") == 2


def test_the_override_uses_the_tag_and_not_an_empty_list() -> None:
    """Measured: a plain empty list merges and the published port survives."""
    assert "ports: []" not in override_document(("postgres",))


def test_the_override_never_mentions_the_projects_own_services() -> None:
    topology = classify_services(MODEL)
    assert "order-ms" not in override_document(topology.infrastructure)


def test_a_service_name_outside_composes_grammar_is_refused() -> None:
    """Names come from a file we did not write and end up inside a document."""
    from engineering_team.services import ComposeError

    with pytest.raises(ComposeError):
        override_document(("db\n    image: evil",))


def test_classification_is_deterministic() -> None:
    reversed_model = {"services": dict(reversed(list(MODEL["services"].items())))}
    assert classify_services(MODEL) == classify_services(reversed_model)


def test_an_unreadable_compose_is_reported_not_guessed(tmp_path: Path) -> None:
    from engineering_team.services import ComposeError, read_compose_model

    (tmp_path / "docker-compose.yml").write_text("this: is: not: compose\n", encoding="utf-8")
    with pytest.raises(ComposeError):
        read_compose_model(tmp_path / "docker-compose.yml")


def test_networks_are_scoped_to_the_run() -> None:
    """A compose file may pin a global network name; two runs must not share it."""
    document = override_document(("db",), ("pedidos-net",), "aset-r1")
    assert "name: aset-r1-pedidos-net" in document
    assert "internal: true" in document


def test_every_declared_network_is_closed_not_only_the_default() -> None:
    """Measured against a real repository: closing `default` closed nothing.

    PruebaNuevosIngresosBackend declares `pedidos-net` and never touches
    `default`, so marking only `default` internal left the services with a route
    out while appearing to isolate them.
    """
    from engineering_team.services import network_names

    model = {
        "services": {"db": {"image": "postgres", "networks": {"pedidos-net": None}}},
        "networks": {"pedidos-net": {"driver": "bridge"}},
    }
    assert network_names(model) == ("pedidos-net",)
    assert "pedidos-net" in override_document(("db",), network_names(model), "aset-r1")


def test_an_external_network_is_left_alone() -> None:
    """It belongs to something else, and compose refuses to redefine it."""
    from engineering_team.services import network_names

    model = {"networks": {"shared": {"external": True}, "own": {}}}
    assert network_names(model) == ("own",)
