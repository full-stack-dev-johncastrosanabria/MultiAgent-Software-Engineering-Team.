"""The production container path owns dependencies before baseline and until exit."""
import subprocess
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from engineering_team import apply_run
from engineering_team.components import Component
from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole, ErrorCode, ToolStatus
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

        def __init__(self, root, run_id, project="", deadline=None):
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
    # These tests exercise the Python-side orchestration (ServiceStack, the
    # component runners), not the real Docker sweep -- so the runtime is
    # faked absent here rather than left to whatever `docker` a machine or a
    # PATH shim happens to expose. Before this, `sweep()` reached the real
    # `subprocess` module unmocked and a hung `docker` on PATH hung these
    # tests too (A-13/B-11), which this isolation removes regardless of what
    # else is on PATH.
    monkeypatch.setattr("engineering_team.docker_labels.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "engineering_team.mcp.quality.build_runner",
        lambda root, _settings, **_kwargs: Runner(root),
    )
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


def test_a_sweep_that_never_got_an_answer_refuses_to_start(
    tmp_path, monkeypatch, infrastructure
):
    """Deferred L1068: the caller's half of T9's typed sweep refusal.

    `sweep` reporting `INFRASTRUCTURE_ERROR` means cleanup is unknown, not
    done, so nothing may start on top of it: no stack, no runner, and a
    `ServiceStartupError` the CLI can carry across the process boundary."""
    events, stacks, runners = infrastructure
    monkeypatch.setattr(apply_run, "sweep", lambda run_id: {
        "containers": [], "networks": [], "volumes": [], "images": [],
        "error_code": ErrorCode.INFRASTRUCTURE_ERROR,
    })

    with (
        pytest.raises(ServiceStartupError) as caught,
        apply_run.open_project_quality(
            tmp_path, Settings(quality_runner="container"), timeout_seconds=30
        ),
    ):
        pytest.fail("nothing may start after an unanswered sweep")

    assert caught.value.code is ErrorCode.INFRASTRUCTURE_ERROR
    assert not stacks and not runners and events == []


def test_a_daemon_that_refuses_the_sweep_listing_refuses_the_start_too(
    tmp_path, monkeypatch, infrastructure
):
    """The same refusal, reached through the real `sweep` by the other way a
    runtime fails to answer (L1069): `docker ps` exiting non-zero at once, as
    it does with the daemon stopped or the socket denied."""
    _, stacks, runners = infrastructure
    monkeypatch.setattr(
        "engineering_team.docker_labels.shutil.which", lambda _name: "/usr/bin/docker"
    )
    monkeypatch.setattr(
        "engineering_team.docker_labels.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, "", "denied"),
    )

    with (
        pytest.raises(ServiceStartupError),
        apply_run.open_project_quality(
            tmp_path, Settings(quality_runner="container"), timeout_seconds=30
        ),
    ):
        pytest.fail("nothing may start after a refused sweep")

    assert not stacks and not runners


def test_a_bind_mount_refusal_reaches_the_caller_as_a_typed_startup_error(
    tmp_path, monkeypatch
):
    """B-11's own example: a compose file that binds outside the checkout is
    refused before anything starts (`_validate_isolation`), and that refusal
    reaches `execute_on_project`'s caller as `ServiceStartupError` -- the one
    type the CLI maps to its infrastructure exit code."""
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.docker_labels.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "engineering_team.services.read_compose_model", lambda _, deadline=None: {
            "services": {"db": {"image": "postgres", "volumes": [{
                "type": "bind", "source": str(tmp_path), "target": "/data",
            }]}},
        },
    )
    monkeypatch.setattr(apply_run, "quality_targets_for", lambda *_: [
        Component(path=".", stack="jvm", manifest="pom.xml"),
    ])

    with (
        pytest.raises(ServiceStartupError) as caught,
        apply_run.open_project_quality(
            root, Settings(quality_runner="container"), timeout_seconds=30
        ),
    ):
        pytest.fail("a refused compose file must not start")

    assert isinstance(caught.value.__cause__, ComposeError)
    assert caught.value.code is ErrorCode.INFRASTRUCTURE_ERROR


def _asets_own_attribute_error(monkeypatch):
    """A bug in ASET's own wiring, after every infrastructure step succeeded."""

    def broken(self, stack, root):
        raise AttributeError("'Stack' object has no attribute 'environment'")

    monkeypatch.setattr("engineering_team.services.ServiceStack.environment_for_component", broken)
    return AttributeError


def _quality_constructor_refusal(monkeypatch):
    """`QualityMCP(...)` refusing its own configuration (a `ValueError`)."""

    def refuse(root, _settings, **_kwargs):
        raise ValueError("container image must be pinned by digest")

    monkeypatch.setattr("engineering_team.mcp.quality.build_runner", refuse)
    return ValueError


@pytest.mark.parametrize(
    "inject", [_asets_own_attribute_error, _quality_constructor_refusal],
    ids=["environment_for_component-bug", "QualityMCP-refusal"],
)
def test_a_failure_after_the_infrastructure_steps_is_not_dressed_as_infrastructure(
    tmp_path, monkeypatch, infrastructure, inject
):
    """N-1: only the infrastructure steps (`sweep`, `ServiceStack(...)`,
    `services.up`, `daemon.up`) may become `ServiceStartupError`. A failure in
    wiring the components on top of a stack that came up -- ASET's own bug or
    its own refusal -- propagates as itself, so the CLI exits as a crash
    instead of with the infrastructure status. Cleanup still runs."""
    events, _, _ = infrastructure
    expected = inject(monkeypatch)

    with (
        pytest.raises(expected) as caught,
        apply_run.open_project_quality(
            tmp_path, Settings(quality_runner="container"), timeout_seconds=30
        ),
    ):
        pytest.fail("the components must not be wired")

    assert not isinstance(caught.value, ServiceStartupError)
    # Torn down all the same: any runner already built is closed, then the stack.
    assert events[0] == "up" and events[-1] == "down" and events.count("down") == 1
    assert "command" not in events


def _run_project_through_the_real_startup(tmp_path, monkeypatch):
    """`engineering-team run-project` down to `_ProjectInfrastructureQuality.
    __enter__`, with only the model runtimes, tracer and repository client
    faked -- none of which the startup path under test touches."""
    from typer.testing import CliRunner

    from engineering_team import cli

    monkeypatch.setattr(apply_run, "MCPRepositoryClient", lambda *a, **k: nullcontext(object()))
    monkeypatch.setattr(apply_run, "LocalModelRuntime", lambda *a, **k: object())
    monkeypatch.setattr(apply_run, "build_retriever", lambda *a, **k: object())
    monkeypatch.setattr(apply_run, "LangfuseTracer", lambda **k: SimpleNamespace(
        start_run=lambda *a: SimpleNamespace(trace_id="test")
    ))
    monkeypatch.setattr(
        cli, "Settings", lambda: Settings(quality_runner="container", cloud_enabled=False)
    )
    return CliRunner().invoke(cli.app, [
        "run-project", str(tmp_path), "--spec", "add endpoint",
        "--report-path", str(tmp_path / "report.json"),
    ])


def test_run_project_exits_as_a_crash_for_an_aset_bug_during_stack_startup(
    tmp_path, monkeypatch, infrastructure
):
    """N-1 at the process boundary, on the real path rather than a patched
    `run_on_project`: the scorer must read this run as `crash`, never as
    `infrastructure_unavailable`."""
    from engineering_team.contracts.enums import INFRASTRUCTURE_EXIT_CODE

    _asets_own_attribute_error(monkeypatch)

    result = _run_project_through_the_real_startup(tmp_path, monkeypatch)

    assert result.exit_code not in (0, INFRASTRUCTURE_EXIT_CODE)
    assert isinstance(result.exception, AttributeError)


def test_run_project_exits_with_the_infrastructure_status_when_a_dependency_never_came_up(
    tmp_path, monkeypatch, infrastructure
):
    """The other half, on the same real path: a failed infrastructure step is
    what the infrastructure status exists for."""
    from engineering_team.contracts.enums import INFRASTRUCTURE_EXIT_CODE

    def fail(self, deadline):
        raise RuntimeError("database unhealthy")

    monkeypatch.setattr("engineering_team.services.ServiceStack.up", fail)

    result = _run_project_through_the_real_startup(tmp_path, monkeypatch)

    assert result.exit_code == INFRASTRUCTURE_EXIT_CODE


def test_a_run_daemon_that_never_came_up_is_an_infrastructure_failure(
    tmp_path, monkeypatch, infrastructure
):
    """The fourth infrastructure step, pinned like the sweep, the compose read
    and `services.up`: without this, unwrapping `daemon.up` left every test
    green and a daemon that never came up read as an ASET crash."""
    from engineering_team.mcp.run_daemon import RunDaemon, RunDaemonStartupError

    events, _, runners = infrastructure

    def fail(self, deadline):
        raise RunDaemonStartupError("run daemon startup deadline exceeded")

    monkeypatch.setattr(RunDaemon, "up", fail)
    monkeypatch.setattr(RunDaemon, "down", lambda self: events.append("daemon-down"))
    settings = Settings(
        quality_runner="container",
        quality_run_daemon_image="docker@sha256:" + "0" * 64,
    )

    with (
        pytest.raises(
            ServiceStartupError, match="INFRASTRUCTURE_ERROR: run daemon startup deadline"
        ) as caught,
        apply_run.open_project_quality(tmp_path, settings, timeout_seconds=30),
    ):
        pytest.fail("the components must not be wired")

    assert isinstance(caught.value.__cause__, RunDaemonStartupError)
    assert events == ["up", "daemon-down", "down"]
    assert not runners


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interrupted_start_cleans_and_preserves_interruption(
    tmp_path, monkeypatch, infrastructure, interruption
):
    events, _, runners = infrastructure
    failure = interruption("cancelled startup")

    def interrupt(self, deadline):
        events.append("up")
        raise failure

    monkeypatch.setattr("engineering_team.services.ServiceStack.up", interrupt)
    handle = apply_run.open_project_quality(
        tmp_path, Settings(quality_runner="container"), timeout_seconds=30
    )
    with pytest.raises(interruption) as caught, handle:
        pytest.fail("baseline must not run")
    assert caught.value is failure
    handle.close()
    assert events == ["up", "down"]
    assert not runners


def test_declared_compose_environment_matches_build_context(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
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
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
        "services": {"db": {"image": "postgres", **service}}
    })
    with pytest.raises(ComposeError):
        ServiceStack(tmp_path, "test")


@pytest.mark.parametrize("source_kind", ["absolute", "relative", "symlink"])
@pytest.mark.parametrize("read_only", [False, True])
def test_bind_outside_checkout_is_refused(tmp_path, monkeypatch, source_kind, read_only):
    root = tmp_path / "checkout"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "compose.yaml").write_text("services: {}")
    (root / "link").symlink_to(outside, target_is_directory=True)
    source = {"absolute": str(outside), "relative": "../outside", "symlink": "./link"}[
        source_kind
    ]
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
        "services": {"db": {"image": "postgres", "volumes": [{
            "type": "bind", "source": source, "target": "/data", "read_only": read_only,
        }]}}
    })
    with pytest.raises(ComposeError, match="bind outside the project checkout"):
        ServiceStack(root, "test")


def test_bind_inside_checkout_is_available_for_database_initialization(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    (tmp_path / "init.sql").write_text("CREATE DATABASE orders;")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
        "services": {"db": {"image": "postgres", "volumes": [{
            "type": "bind", "source": str(tmp_path / "init.sql"),
            "target": "/docker-entrypoint-initdb.d/init.sql", "read_only": True,
        }]}}
    })
    assert ServiceStack(tmp_path, "test").services == ("db",)


def test_volume_driver_cannot_escape_checkout_by_renaming_a_bind(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
        "services": {"db": {"image": "postgres", "volumes": [{
            "type": "volume", "source": "database", "target": "/data",
        }]}},
        "volumes": {"database": {
            "driver": "local", "driver_opts": {"type": "none", "o": "bind", "device": "/tmp"},
        }},
    })
    with pytest.raises(ComposeError, match="non-isolated driver options"):
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
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
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
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
        "services": {
            "one": {"build": ".", "environment": {"DB_HOST": "database-one"}},
            "two": {"build": ".", "environment": {"DB_HOST": "database-two"}},
        }
    })
    with pytest.raises(ComposeError, match="conflicting Compose environment key DB_HOST"):
        ServiceStack(tmp_path, "test").environment_for_component("jvm", tmp_path)


def test_shared_maven_context_merges_compatible_service_environment(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
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
    monkeypatch.setattr("engineering_team.services.read_compose_model", lambda _, deadline=None: {
        "services": {
            "kafka": {"image": "apache/kafka:4.3.1"},
            "kafka-init": {"image": "apache/kafka:4.3.1"},
            "postgres": {"image": "postgres:17"},
        },
        "networks": {"pedidos-net": {}, "admin-net": {}},
        "volumes": {"postgres-data": {}, "kafka-data": {}},
    })
    # The compose project is the project's name, not the run's (ADR 16): the
    # run id is what the labels carry, and is deliberately not in these names.
    stack = ServiceStack(tmp_path, "apply-3f2a", project="prueba")
    document = override_document(
        stack.services, ("pedidos-net", "admin-net"), stack.project,
        ("postgres-data", "kafka-data"),
        run_id=stack.run_id, slug=stack.slug,
    )
    for service in ("kafka", "kafka-init", "postgres"):
        assert f"container_name: aset-prueba-{service}" in document
    for resource in ("pedidos-net", "admin-net", "postgres-data", "kafka-data"):
        assert f"name: aset-prueba-{resource}" in document
