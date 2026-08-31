"""A component is a directory with a build manifest (ADR 4).

The shapes below are the real path lists of six repositories this system is meant
to be pointed at. None of them is a single stack, which is why a profile attaches
to a component and not to a repository.
"""

from __future__ import annotations

from engineering_team.components import Component, detect_components

PRUEBA = [
    "docker-compose.yml", "init/init.sql",
    "order-ms/pom.xml", "order-ms/Dockerfile",
    "payment-ms/pom.xml", "payment-ms/Dockerfile",
    "frontend/package.json", "frontend/Dockerfile",
]
NORTHGATE = [
    "run.sh", "test.sh", "ARCHITECTURE.md",
    "northgate-backend/pom.xml",
    "northgate-backend/audit-service/pom.xml",
    "northgate-backend/toll-service/pom.xml",
    "northgate-frontend/package.json",
]
BANKING = [
    "Banking.slnx", "README.md",
    "src/Banking.Api/Banking.Api.csproj",
    "src/Banking.Application/Banking.Application.csproj",
    "src/Banking.Domain/Banking.Domain.csproj",
    "src/Banking.Infrastructure/Banking.Infrastructure.csproj",
    "tests/Banking.Tests/Banking.Tests.csproj",
    "banking-web/package.json",
]
BUSINESSAI = [
    "package.json",
    "api-gateway/pom.xml", "analytics-service/pom.xml", "customer-service/pom.xml",
    "database/pom.xml", "product-service/pom.xml", "sales-service/pom.xml",
    "document-service/pom.xml",
    "ai-service/requirements.txt",
    "frontend/package.json",
]
FLASK = ["requirements.txt", "run.py", "pytest.ini", "client/package.json"]


def _stacks(paths: list[str]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for component in detect_components(paths):
        counted[component.stack] = counted.get(component.stack, 0) + 1
    return counted


def test_java_microservices_beside_a_typescript_frontend() -> None:
    assert _stacks(PRUEBA) == {"jvm": 2, "node": 1}


def test_a_parent_pom_is_its_own_component() -> None:
    """An aggregator module builds; it is not a directory to skip."""
    assert _stacks(NORTHGATE) == {"jvm": 3, "node": 1}


def test_dotnet_projects_are_components_and_the_solution_is_not() -> None:
    """A .slnx lists projects; it is not something to build in a directory."""
    assert _stacks(BANKING) == {"dotnet": 5, "node": 1}
    assert not any(c.manifest.endswith((".sln", ".slnx")) for c in detect_components(BANKING))


def test_java_and_python_and_react_in_one_repository() -> None:
    assert _stacks(BUSINESSAI) == {"jvm": 7, "python": 1, "node": 2}


def test_a_manifest_at_the_repository_root_is_the_root_component() -> None:
    components = detect_components(FLASK)
    assert _stacks(FLASK) == {"python": 1, "node": 1}
    assert any(c.path == "" and c.stack == "python" for c in components)


def test_vendored_and_build_output_manifests_are_not_components() -> None:
    """The same discipline the repository listing learned in finding 4."""
    noise = [
        "app/pyproject.toml",
        "app/node_modules/left-pad/package.json",
        "web/node_modules/.bin/pkg/package.json",
        "svc/target/classes/pom.xml",
        "api/bin/Debug/net10.0/App.csproj",
        "api/obj/project.assets.csproj",
        "third_party/vendor/lib/package.json",
        ".venv/lib/python3.14/site-packages/thing/pyproject.toml",
        "dist/package.json",
    ]
    components = detect_components(noise)
    assert [c.path for c in components] == ["app"]


def test_one_directory_with_two_python_manifests_is_one_component() -> None:
    components = detect_components(["svc/pyproject.toml", "svc/requirements.txt"])
    assert len(components) == 1
    assert components[0].stack == "python"


def test_one_directory_serving_two_stacks_is_two_components() -> None:
    components = detect_components(["app/package.json", "app/pyproject.toml"])
    assert {c.stack for c in components} == {"node", "python"}


def test_detection_is_deterministic() -> None:
    shuffled = list(reversed(BUSINESSAI))
    assert detect_components(BUSINESSAI) == detect_components(shuffled)


def test_a_component_reports_the_manifest_that_identified_it() -> None:
    (component,) = detect_components(["svc/pom.xml"])
    assert component == Component(path="svc", stack="jvm", manifest="pom.xml")
