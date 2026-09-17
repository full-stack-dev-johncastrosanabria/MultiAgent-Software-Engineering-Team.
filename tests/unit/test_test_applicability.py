import json
from types import SimpleNamespace

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ToolResult
from engineering_team.mcp.quality import CompositeQuality


def backend(root, workspace, stack, *, status=ToolStatus.SUCCESS):
    root.mkdir(parents=True, exist_ok=True)
    calls = []
    result = ToolResult(
        tool_name="run_tests", allowed_role=AgentRole.TESTING, status=status,
        input_summary="default suite", output_summary="62 passed",
        duration_ms=1,
        evidence_reference=f"mcp://quality/run_tests#{root.name}",
    )
    return SimpleNamespace(
        root=root, workspace_root=workspace, component=root.name,
        profile=SimpleNamespace(name=stack), test_filter="", calls=calls,
        run_tests=lambda role, paths=None: calls.append(paths) or result,
        get_test_results=lambda role: result.model_copy(update={"tool_name": "get_test_results"}),
    )


def project(tmp_path, manifest=None):
    server = backend(tmp_path / "server", tmp_path, "python")
    client = backend(tmp_path / "client", tmp_path, "node", status=ToolStatus.FAIL)
    (client.root / "package.json").write_text(json.dumps(manifest or {"scripts": {"build": "vite build"}}))
    quality = CompositeQuality([server, client])
    quality.set_changed_paths([])
    return quality, server, client


def test_unchanged_component_without_tests_is_reported_but_not_executed(tmp_path):
    quality, server, client = project(tmp_path)
    quality.set_changed_paths(["server/app.py", "server/tests/test_filter.py"])
    result = quality.run_tests(AgentRole.TESTING)
    assert result.status is ToolStatus.SUCCESS
    assert len(server.calls) == 1 and not client.calls
    assert "client" in result.output_summary and "no test command" in result.output_summary
    assert len(quality.last_component_results) == 1
    assert quality.get_test_results(AgentRole.TESTING).status is ToolStatus.SUCCESS


@pytest.mark.parametrize("path", ["client/src/app.ts", "client/package.json", "../unknown", "."])
def test_changed_or_unknown_scope_cannot_omit_a_component(tmp_path, path):
    quality, _, client = project(tmp_path)
    quality.set_changed_paths([path])
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.FAIL
    assert len(client.calls) == 1


@pytest.mark.parametrize("declared", ["script", "source", "malformed", "filter"])
def test_existing_test_declarations_are_never_silently_omitted(tmp_path, declared):
    quality, _, client = project(tmp_path)
    if declared == "script":
        (client.root / "package.json").write_text('{"scripts":{"test":"vitest run"}}')
    elif declared == "source":
        (client.root / "app.spec.ts").write_text("test('original', () => {});")
    elif declared == "malformed":
        (client.root / "package.json").write_text('{')
    else:
        client.test_filter = "original"
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.FAIL
    assert len(client.calls) == 1


def test_no_suite_executed_cannot_be_green(tmp_path):
    _, _, client = project(tmp_path)
    quality = CompositeQuality([client])
    quality.set_changed_paths([])
    result = quality.run_tests(AgentRole.TESTING)
    assert result.status is ToolStatus.UNAVAILABLE
    assert not client.calls
    assert "no test suite executed" in result.output_summary


def test_component_is_reassessed_after_new_tests_are_written(tmp_path):
    quality, _, client = project(tmp_path)
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.SUCCESS
    (client.root / "new.test.ts").write_text("test('new', () => {});")
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.FAIL
    assert len(client.calls) == 1


@pytest.mark.parametrize("declaration", [
    "vitest.config.ts", "jest.config.js", "playwright.config.ts", "karma.conf.js",
    "script:test:unit", "script:test:e2e", "package:jest",
])
def test_alternate_test_declarations_prevent_omission(tmp_path, declaration):
    quality, _, client = project(tmp_path)
    if declaration.startswith("script:"):
        package = {"scripts": {declaration[7:]: "test-runner"}}
        (client.root / "package.json").write_text(json.dumps(package))
    elif declaration.startswith("package:"):
        (client.root / "package.json").write_text('{"jest":{}}')
    else:
        (client.root / declaration).write_text("export default {};")
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.FAIL
    assert len(client.calls) == 1


def test_unknown_change_scope_does_not_authorize_omission(tmp_path):
    _, server, client = project(tmp_path)
    quality = CompositeQuality([server, client])
    assert quality.run_tests(AgentRole.TESTING).status is ToolStatus.FAIL
    assert len(client.calls) == 1
