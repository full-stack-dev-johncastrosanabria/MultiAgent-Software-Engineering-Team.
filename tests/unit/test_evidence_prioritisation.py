"""Which files a bounded reading budget spends itself on.

Architecture reads a ranked slice of the repository and designs against it. On
`InterviewCleanApi` it read ten files, none of them backend, and the Reviewer
rejected the design for being built on 7% of the relevant evidence. The ranking
was not close to right: it had never been told that `.cs` is code.
"""

from __future__ import annotations

from engineering_team.agents.architecture import ArchitectureAgent
from engineering_team.components import EXCLUDED_DIRECTORIES, is_excluded

_DOTNET_TREE = [
    "InterviewCleanApi.Domain/Entities/Product.cs",
    "InterviewCleanApi.Domain/Errors/DomainErrors.cs",
    "InterviewCleanApi.Infrastructure/Services/ProductService.cs",
    "InterviewCleanApi.Api/InterviewCleanApi.Api.csproj",
    "clients/vue-client/src/main.ts",
    "clients/vue-client/vite.config.ts",
    "clients/react-client/src/App.tsx",
    "clients/vue-client/src/services/productService.ts",
    "clients/react-client/src/services/productService.ts",
]


def test_a_language_the_ranker_does_not_know_loses_every_tie() -> None:
    """Omitting a suffix does not cost a file a little. It hands two points to
    every file written in a language that is listed, so a .NET repository put
    three front-ends above its own domain for a task about that domain."""
    ranked = ArchitectureAgent.rank_paths(_DOTNET_TREE, [], ["product"])

    assert ranked[0] == "InterviewCleanApi.Domain/Entities/Product.cs"


def test_a_project_file_counts_as_a_manifest() -> None:
    ranked = ArchitectureAgent.rank_paths(
        ["InterviewCleanApi.Api/InterviewCleanApi.Api.csproj", "notes/readme.txt"],
        [],
        [],
    )

    assert ranked[0].endswith(".csproj")


def test_a_named_type_is_a_boundary_even_without_a_path_or_a_route() -> None:
    """A specification names types: "Product gains a factory", "DomainErrors
    already declares them". Matching only literal paths and HTTP routes left a
    domain task with no mandatory evidence at all, and its own entity was never
    required reading."""
    requirement = (
        "Enforce the Product invariants in the entity. DomainErrors already "
        "declares NameRequired, and the service should delegate to it."
    )

    boundaries = ArchitectureAgent.task_boundary_paths(_DOTNET_TREE, requirement)

    assert "InterviewCleanApi.Domain/Entities/Product.cs" in boundaries
    assert "InterviewCleanApi.Domain/Errors/DomainErrors.cs" in boundaries


def test_an_ambiguous_name_is_not_resolved_by_guessing() -> None:
    """Three files are called `productService` here -- one backend, two
    front-ends. Choosing among them is the guess this function exists to avoid,
    and a wrong mandatory file fails the run for the wrong reason. Ranking still
    favours them; they are simply not made mandatory."""
    requirement = "ProductService should delegate validation to the entity."

    boundaries = ArchitectureAgent.task_boundary_paths(_DOTNET_TREE, requirement)

    assert not [path for path in boundaries if path.casefold().endswith("productservice.cs")]
    assert not [path for path in boundaries if path.casefold().endswith("productservice.ts")]


def test_a_name_that_matches_something_that_is_not_code_is_not_a_boundary() -> None:
    tree = ["InterviewCleanApi.Api/InterviewCleanApi.http", "Api/Program.cs"]

    assert ArchitectureAgent.task_boundary_paths(
        tree, "InterviewCleanApi exposes the products endpoint"
    ) == []


def test_the_gate_s_own_reports_do_not_compete_with_the_source() -> None:
    """The dotnet profile writes TRX reports into `TestResults`, so a run
    produced evidence that outranked the repository on the next cycle."""
    assert "TestResults" in EXCLUDED_DIRECTORIES
    assert is_excluded("InterviewCleanApi.Tests/TestResults/run_2026.trx")
    assert not is_excluded("InterviewCleanApi.Tests/ProductsControllerTests.cs")
