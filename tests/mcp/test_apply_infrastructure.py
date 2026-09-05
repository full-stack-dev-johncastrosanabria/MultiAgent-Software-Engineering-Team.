"""The production container path owns dependencies before baseline and until exit."""
import subprocess
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from engineering_team import apply_run
from engineering_team.components import Component
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.services import (
    ComposeError,
    ServiceStack,
    ServiceStartupError,
    override_document,
)


@pytest.fixture
def infrastructure(tmp_path, monkeypatch):
    events = []
    stacks = []
    runners = []

    class Stack:
        services = ("db",)
        network = "aset-test-default"
        networks = ("aset-test-default", "aset-test-admin")

        def __init__(self, root, run_id):
            assert root == tmp_path
            stacks.append(self)

        def up(self, deadline):
            events.append("up")

        def environment_for_component(self, stack, root):
            return (("DB_HOST", "db"), ("COMPONENT", root.name))

        def down(self):
            events.append("down")

    class Runner:
        environment = None
        closing = False
        network = None
        networks = ()

        def __init__(self, root):
            self.root = root
            runners.append(self)

        def execute(self, request):
            assert self.network == Stack.network
            assert self.networks == Stack.networks
            assert dict(request.env)["DB_HOST"] == "db"
            assert dict(request.env)["COMPONENT"] == self.root.name
            assert events[0] == "up"
            assert "down" not in events
            events.append("command")
            return subprocess.CompletedProcess(request.args, 0, "ok", "")

        def close(self):
            events.append("close")

    monkeypatch.setattr("engineering_team.services.ServiceStack", Stack)
    monkeypatch.setattr("engineering_team.mcp.quality.build_runner", lambda root, _: Runner(root))
    monkeypatch.setattr(apply_run, "quality_targets_for", lambda *_: [
        Component(path="one", stack="jvm", manifest="pom.xml"),
        Component(path="two", stack="jvm", manifest="pom.xml"),
    ])
    return events, stacks, runners


def test_apply_starts_once_before_baseline_and_cleans_after_graph_failure(
    tmp_path, monkeypatch, infrastructure
):
    events, stacks, runners = infrastructure
    monkeypatch.setattr(apply_run, "MCPRepositoryClient", lambda *a, **k: nullcontext(object()))
    monkeypatch.setattr(apply_run, "LocalModelRuntime", lambda *a, **k: object())
    monkeypatch.setattr(apply_run, "build_retriever", lambda *a, **k: object())
    monkeypatch.setattr(apply_run, "LangfuseTracer", lambda **k: SimpleNamespace(
        start_run=lambda *a: SimpleNamespace(trace_id="test")
    ))

    class Graph:
        def stream(self, *args, **kwargs):
            assert events.count("command") >= 2  # Real baseline has exercised both runners.
            assert events.count("up") == 1
            raise RuntimeError("graph failed")

    monkeypatch.setattr(apply_run, "build_engineering_graph", lambda **k: Graph())
    with pytest.raises(RuntimeError, match="graph failed"):
        apply_run.execute_on_project(
            Settings(quality_runner="container", cloud_enabled=False),
            project_path=tmp_path, specification="test infrastructure",
        )
    assert len(stacks) == 1
    assert len(runners) == 2
    assert events[-3:] == ["close", "close", "down"]
    assert events.count("down") == 1


def test_success_keeps_shared_stack_until_context_exit(tmp_path, infrastructure):
    events, _, _ = infrastructure
    handle = apply_run.open_project_quality(
        tmp_path, Settings(quality_runner="container"), timeout_seconds=30
    )
    with handle as quality:
        assert quality.run_tests(AgentRole.TESTING).status == ToolStatus.SUCCESS
        assert events.count("up") == 1
        assert "down" not in events
    handle.close()
    assert events.count("down") == 1


def test_failed_start_cleans_and_reports_infrastructure(tmp_path, monkeypatch, infrastructure):
    events, _, runners = infrastructure

    def fail(self, deadline):
        events.append("up")
        raise RuntimeError("database unhealthy")

    monkeypatch.setattr("engineering_team.services.ServiceStack.up", fail)
    with (
        pytest.raises(ServiceStartupError, match="INFRASTRUCTURE_ERROR: database unhealthy"),
        apply_run.open_project_quality(
            tmp_path, Settings(quality_runner="container"), timeout_seconds=30
        ),
    ):
        pytest.fail("baseline must not run")
    assert events == ["up", "down"]
    assert not runners


def test_declared_compose_environment_matches_build_context(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _: {
        "services": {
            "db": {"image": "postgres"},
            "app": {"build": {"context": str(tmp_path / "api")},
                    "environment": {"DB_HOST": "db", "OTHER": None}},
            "web": {"build": {"context": "./web"}, "environment": {"DB_HOST": "other"}},
        }
    })
    stack = ServiceStack(tmp_path, "test")
    assert stack.environment_for_component("jvm", tmp_path / "api") == (("DB_HOST", "db"),)
    assert stack.environment_for_component("node", tmp_path / "web") == (("DB_HOST", "other"),)
    assert stack.environment_for_component("jvm", tmp_path / "unknown") == ()


@pytest.mark.parametrize("service", [
    {"privileged": True}, {"network_mode": "host"},
    {"volumes": [{"type": "bind", "source": "/var/run/docker.sock"}]},
    {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]},
])
def test_declared_unsafe_infrastructure_is_refused(tmp_path, monkeypatch, service):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _: {
        "services": {"db": {"image": "postgres", **service}}
    })
    with pytest.raises(ComposeError):
        ServiceStack(tmp_path, "test")


def test_declared_database_mapping_uses_image_and_supports_both_spring_versions(
    tmp_path, monkeypatch
):
    (tmp_path / "compose.yaml").write_text("services: {}")
    (tmp_path / "application.properties").write_text(
        "spring.mongodb.uri=mongodb://localhost:27017/orders\n"
        "spring.datasource.url=jdbc:postgresql://localhost:5432/orders\n"
        "spring.datasource.username=app\n"
        "spring.datasource.password=test\n"
    )
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _: {
        "services": {
            "documents": {"image": "mongo:7"},
            "database": {"image": "postgres:16"},
        }
    })
    stack = ServiceStack(tmp_path, "test")
    env = dict(stack.environment_for_component("jvm", tmp_path))
    assert env["SPRING_DATASOURCE_URL"] == "jdbc:postgresql://database:5432/orders"
    assert env["SPRING_DATA_MONGODB_URI"] == "mongodb://documents:27017/orders"
    assert env["SPRING_MONGODB_URI"] == env["SPRING_DATA_MONGODB_URI"]


def test_ambiguous_build_context_fails_instead_of_selecting_arbitrary_env(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _: {
        "services": {
            "one": {"build": ".", "environment": {"DB_HOST": "database-one"}},
            "two": {"build": ".", "environment": {"DB_HOST": "database-two"}},
        }
    })
    with pytest.raises(ComposeError, match="conflicting Compose environment key DB_HOST"):
        ServiceStack(tmp_path, "test").environment_for_component("jvm", tmp_path)


def test_shared_maven_context_merges_compatible_service_environment(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _: {
        "services": {
            "postgres": {"image": "postgres"},
            "mongo": {"image": "mongo"},
            "toll": {"build": {"context": "./backend", "args": {"SERVICE": "toll"}},
                     "environment": {"DB_HOST": "postgres", "JWT_SECRET": "same-value"}},
            "audit": {"build": {"context": "./backend", "args": {"SERVICE": "audit"}},
                      "environment": {"MONGO_HOST": "mongo", "JWT_SECRET": "same-value",
                                      "OPTIONAL": None}},
        }
    })
    stack = ServiceStack(tmp_path, "test")
    assert dict(stack.environment_for_component("jvm", tmp_path / "backend")) == {
        "DB_HOST": "postgres", "MONGO_HOST": "mongo", "JWT_SECRET": "same-value",
    }


def test_prueba_services_get_isolated_names_without_rejecting_multiple_networks(
    tmp_path, monkeypatch
):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _: {
        "services": {
            "kafka": {"image": "apache/kafka:4.3.1"},
            "kafka-init": {"image": "apache/kafka:4.3.1"},
            "postgres": {"image": "postgres:17"},
        },
        "networks": {"pedidos-net": {}, "admin-net": {}},
        "volumes": {"postgres-data": {}, "kafka-data": {}},
    })
    stack = ServiceStack(tmp_path, "prueba")
    document = override_document(
        stack.services, ("pedidos-net", "admin-net"), stack.project,
        ("postgres-data", "kafka-data"),
    )
    for service in ("kafka", "kafka-init", "postgres"):
        assert f"container_name: aset-prueba-{service}" in document
    for resource in ("pedidos-net", "admin-net", "postgres-data", "kafka-data"):
        assert f"name: aset-prueba-{resource}" in document
