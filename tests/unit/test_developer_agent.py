import pytest
from pydantic import ValidationError

from engineering_team.agents.developer import DeveloperAgent
from engineering_team.contracts.enums import ActionMode, AgentRole, ToolStatus
from engineering_team.contracts.models import (
    ArchitectureProposal,
    ImplementationResult,
    ProductSpecification,
    ToolResult,
)
from engineering_team.contracts.state import EngineeringState
from engineering_team.models.context import build_context


def test_developer_proposal_is_detailed_and_grounded_in_inspected_paths() -> None:
    specification = ProductSpecification(
        objective="Add an authorized transaction-history endpoint",
        actors=["User"],
        business_rules=["return at most five owned transactions"],
        constraints=["preserve authorization"],
        acceptance_criteria=["ownership is enforced"],
        nfrs=["secure"],
        ambiguities=[],
        assumptions=[],
        source_requirement="Return five transactions for the authorized user",
    )
    architecture = ArchitectureProposal(
        components=["transaction API"],
        apis=["GET /transactions"],
        data_changes=["owner-scoped query limit"],
        integrations=[],
        dependencies=[],
        decisions=["enforce ownership before limiting to five"],
        risks=["IDOR"],
        impact="bounded API change",
    )
    inspected = ["app/api.py", "app/models.py"]
    state = EngineeringState(
        run_id="developer-proposal",
        requirement=specification.source_requirement,
        specification=specification,
        architecture=architecture,
        tool_results=[
            ToolResult(
                tool_name="list_files",
                allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS,
                input_summary="safe",
                output_summary="\n".join(inspected),
                duration_ms=3,
                evidence_reference="mcp://repository/list_files",
            ),
            *[
                ToolResult(
                    tool_name="read_file",
                    allowed_role=AgentRole.DEVELOPER,
                    status=ToolStatus.SUCCESS,
                    input_summary=f"path={path}",
                    output_summary="def transaction_history(owner_id):\n    pass\n",
                    duration_ms=2,
                    evidence_reference="mcp://repository/read_file",
                )
                for path in inspected
            ],
        ],
    )

    result = DeveloperAgent().execute(build_context(AgentRole.DEVELOPER, state, "Developer"))

    assert result.changed_files
    assert set(result.changed_files) <= set(inspected)
    assert "GET /transactions" in result.diff
    assert "owner-scoped query limit" in result.diff
    assert "mcp://repository/list_files" in result.evidence
    assert any("mcp://repository/read_file#" in item for item in result.evidence)
    assert "run_build" in result.validation_result
    assert "run_linter" in result.validation_result
    assert "run_tests" in result.validation_result
    assert result.security_surface_changed is True


def test_developer_contract_rejects_unjustified_empty_proposal() -> None:
    with pytest.raises(ValidationError, match="no-op justification"):
        ImplementationResult(
            action_mode=ActionMode.PROPOSED,
            changed_files=[],
            diff="",
            evidence=[],
            validation_result="not applied",
        )


def test_requested_targets_adds_a_constant_test_when_requirement_requires_one() -> None:
    targets = DeveloperAgent.requested_targets(
        "Agrega en calculadora/__init__.py una constante pública llamada VERSION "
        "con el valor entero 2. Agrega una prueba en tests/ que verifique calculadora.VERSION."
    )

    assert targets == ["calculadora/__init__.py", "tests/test_version.py"]


def test_requested_targets_resolves_unique_java_symbols_from_repository_paths() -> None:
    """The Java run named classes, not literal paths, and consequently wrote nothing."""
    targets = DeveloperAgent.requested_targets(
        (
            "Agrega GET /api/v1/orders/stats en OrderController y pruebas en "
            "OrderControllerTest para todos los valores de OrderStatus."
        ),
        repository_paths=[
            "order-ms/src/main/java/com/prueba/orderms/domain/OrderStatus.java",
            "order-ms/src/main/java/com/prueba/orderms/web/OrderController.java",
            "order-ms/src/test/java/com/prueba/orderms/web/OrderControllerTest.java",
            "payment-ms/src/main/java/com/prueba/paymentms/PaymentController.java",
        ],
    )

    assert targets == [
        "order-ms/src/main/java/com/prueba/orderms/web/OrderController.java",
        "order-ms/src/test/java/com/prueba/orderms/web/OrderControllerTest.java",
        "order-ms/src/main/java/com/prueba/orderms/domain/OrderStatus.java",
    ]


def test_requested_targets_does_not_authorize_an_ambiguous_symbol() -> None:
    targets = DeveloperAgent.requested_targets(
        "Actualiza OrderController.",
        repository_paths=[
            "orders/src/main/java/example/OrderController.java",
            "admin/src/main/java/example/OrderController.java",
        ],
    )

    assert targets == []


def test_search_terms_prioritize_identifiers_and_business_fields_over_generic_verbs() -> None:
    specification = ProductSpecification(
        objective=(
            "Implementar endpoint GET /api/products/low-stock con threshold y "
            "restock_value calculado a partir de cost"
        ),
        actors=[], business_rules=["restock_value usa cost y stock"], constraints=[],
        acceptance_criteria=[], nfrs=[], ambiguities=[], assumptions=[],
        source_requirement="Implementar endpoint de stock bajo",
    )
    architecture = ArchitectureProposal(
        components=["Product (app/models/product.py)"], apis=[], data_changes=[],
        integrations=[], dependencies=[], decisions=[], risks=[], impact="bounded",
    )

    terms = DeveloperAgent.search_terms(specification, architecture, "Implementar endpoint")

    assert {"restock_value", "threshold", "cost"} <= set(terms[:6])
    assert "implementar" not in terms[:6]
    assert "endpoint" not in terms[:6]


def test_dependency_targets_follow_only_unique_local_java_imports() -> None:
    controller = "order-ms/src/main/java/com/example/orders/OrderController.java"
    service = "order-ms/src/main/java/com/example/orders/OrderService.java"
    repository = "order-ms/src/main/java/com/example/orders/OrderRepository.java"
    paths = [
        controller,
        service,
        repository,
        "billing-ms/src/main/java/com/example/billing/OrderService.java",
    ]

    first_wave = DeveloperAgent.dependency_targets(
        paths,
        {
            controller: (
                "import com.example.orders.OrderService;\n"
                "import org.springframework.http.ResponseEntity;\n"
                "public class OrderController {}\n"
            ),
        },
        already_read={controller},
    )

    # The duplicated OrderService basename is disambiguated by the fully-qualified import.
    assert first_wave == [service]

    second_wave = DeveloperAgent.dependency_targets(
        paths,
        {
            controller: "import com.example.orders.OrderService;\n",
            service: "import com.example.orders.OrderRepository;\n",
        },
        already_read={controller, service},
    )

    assert second_wave == [repository]


def test_apply_adds_one_relevant_inspected_source_when_only_a_test_is_named() -> None:
    """A feature request must not authorize only its test by accident.

    FlaskApiProduct named ``tests/test_products.py`` in the test specification.
    Apply consequently forbade the endpoint file even though Repository MCP had
    inspected it, so the model could only write failing tests.
    """
    specification = ProductSpecification(
        objective="Add the low-stock products endpoint",
        actors=["Catalog user"],
        business_rules=["filter products by a stock threshold"],
        constraints=[],
        acceptance_criteria=["GET /api/products/low-stock returns matching products"],
        nfrs=[], ambiguities=[], assumptions=[],
        source_requirement="Add a low-stock endpoint and tests/test_products.py coverage",
    )
    architecture = ArchitectureProposal(
        components=["products route"], apis=["GET /api/products/low-stock"],
        data_changes=[], integrations=[], dependencies=[],
        decisions=["extend the products route"], risks=[], impact="bounded route change",
    )
    state = EngineeringState(
        run_id="apply-source", requirement=specification.source_requirement,
        specification=specification, architecture=architecture,
        repository_context={"apply_changes": True},
        tool_results=[
            ToolResult(
                tool_name="read_file", allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS, input_summary="path=app/routes/products.py",
                output_summary="@bp.route('/api/products')\ndef get_products(): pass\n",
                duration_ms=1, evidence_reference="mcp://repository/read_file",
            ),
            ToolResult(
                tool_name="read_file", allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS, input_summary="path=tests/test_products.py",
                output_summary="def test_get_products_empty(): pass\n",
                duration_ms=1, evidence_reference="mcp://repository/read_file",
            ),
        ],
    )

    result = DeveloperAgent().execute(build_context(AgentRole.DEVELOPER, state, "Developer"))

    assert result.changed_files == ["app/routes/products.py", "tests/test_products.py"]


def test_apply_adds_source_when_test_request_also_contains_auxiliary_documentation() -> None:
    """A changelog must not prevent the route behind a named test from changing."""
    specification = ProductSpecification(
        objective="Add the low-stock products endpoint",
        actors=[], business_rules=[], constraints=[], acceptance_criteria=[],
        nfrs=[], ambiguities=[], assumptions=[],
        source_requirement="Add tests/test_products.py coverage",
    )
    architecture = ArchitectureProposal(
        components=[], apis=[], data_changes=[], integrations=[], dependencies=[],
        decisions=[], risks=[], impact="bounded route change",
    )
    requested = DeveloperAgent.apply_targets(
        ["CHANGELOG.md", "tests/test_products.py"],
        [
            ToolResult(
                tool_name="read_file", allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS, input_summary="path=app/ai/knowledge_base.py",
                output_summary="base " * 100, duration_ms=1,
            ),
            ToolResult(
                tool_name="read_file", allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS, input_summary="path=app/routes/products.py",
                output_summary="def get_products(): pass\n", duration_ms=1,
            ),
        ],
        specification,
        architecture,
        specification.source_requirement,
    )

    assert requested == ["app/routes/products.py", "CHANGELOG.md", "tests/test_products.py"]


def test_developer_selects_inspected_transaction_module_not_first_listed_paths() -> None:
    specification = ProductSpecification(
        objective="Return the latest five transactions for the authorized owner",
        actors=["User"],
        business_rules=["scope history by owner_id", "limit results to five"],
        constraints=["prevent IDOR"],
        acceptance_criteria=["cross-user access is denied"],
        nfrs=["secure"], ambiguities=[], assumptions=[],
        source_requirement="authorized transaction history limited to five",
    )
    architecture = ArchitectureProposal(
        components=["transaction service"], apis=["GET /transactions"],
        data_changes=["owner-scoped query with limit 5"], integrations=[], dependencies=[],
        decisions=["authorize owner before querying"], risks=["IDOR"],
        impact="bounded API and query change",
    )
    listed = "README.md\n__init__.py\nmisc.py\napp/transactions.py"
    code = (
        "def transaction_history(connection, owner_id):\n"
        "    return connection.execute('SELECT * FROM transactions').fetchall()\n"
    )
    state = EngineeringState(
        run_id="relevance", requirement=specification.source_requirement,
        specification=specification, architecture=architecture,
        tool_results=[
            ToolResult(
                tool_name="list_files", allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS, input_summary="safe", output_summary=listed,
                duration_ms=1, evidence_reference="mcp://repository/list_files",
            ),
            ToolResult(
                tool_name="search_code", allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS, input_summary="query=transaction",
                output_summary="app/transactions.py", duration_ms=1,
                evidence_reference="mcp://repository/search_code",
            ),
            ToolResult(
                tool_name="read_file", allowed_role=AgentRole.DEVELOPER,
                status=ToolStatus.SUCCESS, input_summary="path=app/transactions.py",
                output_summary=code, duration_ms=1,
                evidence_reference="mcp://repository/read_file",
            ),
        ],
    )

    result = DeveloperAgent().execute(build_context(AgentRole.DEVELOPER, state, "Developer"))

    assert result.changed_files == ["app/transactions.py"]
    assert "transaction_history" in result.diff
    assert "owner_id" in result.diff
    assert "GET /transactions" in result.diff
    assert "owner-scoped query with limit 5" in result.diff
    assert "Implement the bounded change above" not in result.diff
    assert any("read_file" in item for item in result.evidence)
    assert result.security_surface_changed is True


def test_developer_refuses_credential_paths_architecture_already_rejects() -> None:
    """El Developer manda el contenido crudo al prompt, sin saneador: no puede
    sanearlo porque debe reescribir el archivo fiel. Entonces el control es no
    leerlo. Estas rutas ya las rechazaba Architecture."""
    for path in (
        ".ssh/id_rsa",
        "id_rsa",
        "credentials.json",
        ".aws/credentials",
        "secrets/db.yaml",
        ".npmrc",
        ".pypirc",
        "id_ed25519",
    ):
        assert not DeveloperAgent._safe_path(path), path


def test_developer_still_accepts_ordinary_source_and_new_files() -> None:
    for path in ("src/app.py", "tests/test_app.py", "deploy/backup.yaml", "README.md"):
        assert DeveloperAgent._safe_path(path), path
