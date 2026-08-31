import json

import pytest

from engineering_team.agents.product import ProductAgent
from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    ReviewerStatus,
    RouteTarget,
    ToolStatus,
)
from engineering_team.contracts.models import (
    ImplementationResult,
    ReviewerDecision,
    ToolResult,
)
from engineering_team.contracts.state import EngineeringState
from engineering_team.llm.prompting import build_role_prompts, governed_output_schema
from engineering_team.models.context import build_context


@pytest.mark.parametrize("role", list(AgentRole))
def test_consumed_system_prompt_declares_role_boundaries_evidence_and_authority(role) -> None:
    state = EngineeringState(run_id="prompt", requirement="safe bounded change")
    candidate = ProductAgent().execute(build_context(AgentRole.PRODUCT, state, "Product"))
    envelope = build_context(role, state, role.value)

    system, _ = build_role_prompts(
        role, envelope, type(candidate), candidate.model_dump(mode="json")
    )

    assert f"ROLE: {role.value}" in system
    assert "RESPONSIBILITY:" in system
    assert "BOUNDARIES:" in system
    assert "EVIDENCE TO PRESERVE:" in system
    assert "OUTPUT CONTRACT:" in system
    assert "NO ROUTING / NO MODEL SELECTION:" in system


def test_prompt_does_not_present_a_truncated_requirement_as_the_canonical_one():
    requirement = "Implement a small banking operation. " * 12 + "Require authenticated ownership."
    state = EngineeringState(run_id="prompt", requirement=requirement)
    envelope = build_context(AgentRole.PRODUCT, state, "Product")
    candidate = ProductAgent().execute(envelope)
    _, user = build_role_prompts(AgentRole.PRODUCT, envelope, type(candidate), candidate.model_dump(mode="json"))
    context_line = next(line for line in user.splitlines() if line.startswith("ContextEnvelope: "))
    context = json.loads(context_line.removeprefix("ContextEnvelope: "))
    assert context["state_projection"]["requirement"] == requirement


def test_developer_reads_source_with_real_line_breaks_not_nested_json_escapes():
    source = 'def login(password: str):\n    return verify(password)\n'
    state = EngineeringState(run_id="prompt", requirement="Edit app.py", tool_results=[ToolResult(
        tool_name="read_file", allowed_role=AgentRole.DEVELOPER, status=ToolStatus.SUCCESS,
        input_summary="path=app.py", output_summary=source, duration_ms=0,
    )])
    envelope = build_context(AgentRole.DEVELOPER, state, "Developer")
    _, user = build_role_prompts(AgentRole.DEVELOPER, envelope, {}, {"action_mode": "APPLIED"})
    assert source in user
    assert "```python" in user
    from engineering_team.guardrails.secrets import require_safe_cloud_context
    require_safe_cloud_context(user)


def test_remediation_prompt_uses_latest_read_of_each_file_and_preserves_audit():
    tools = [ToolResult(tool_name="read_file", allowed_role=AgentRole.DEVELOPER,
                        status=ToolStatus.SUCCESS, input_summary="app.py",
                        output_summary=source, duration_ms=0)
             for source in ["obsolete_value = 1\n", "current_value = 2\n"]]
    state = EngineeringState(run_id="prompt", requirement="Edit app.py", tool_results=tools)
    envelope = build_context(AgentRole.DEVELOPER, state, "Developer")
    _, user = build_role_prompts(AgentRole.DEVELOPER, envelope, {}, {"action_mode": "APPLIED"})
    assert "obsolete_value" not in user
    assert user.count("current_value = 2") == 1
    assert envelope.tool_results == tools


def test_apply_schema_constrains_paths_and_facts_but_leaves_code_to_the_model():
    from engineering_team.contracts.models import ImplementationResult
    candidate = ImplementationResult(action_mode="APPLIED", changed_files=["app.py"],
        diff="planned", evidence=["mcp://read/app.py"], validation_result="pending",
        security_surface_changed=True, file_contents={})
    schema = governed_output_schema(ImplementationResult, candidate.model_dump(mode="json"))
    assert schema["properties"]["changed_files"]["const"] == ["app.py"]
    assert schema["properties"]["evidence"]["const"] == candidate.evidence
    contents = schema["properties"]["file_contents"]
    assert contents["required"] == ["app.py"]
    assert contents["additionalProperties"] is False
    assert contents["properties"]["app.py"] == {"type": "string"}


def test_developer_remediation_prompt_carries_the_code_it_authored():
    """Finding 7: in PROPOSED mode nothing reaches the workspace between cycles.

    The write-back in stategraph only runs for ActionMode.APPLIED, so on a
    remediation pass the Developer re-reads the original files and sees no trace
    of its own work. Adding `implementation` to the projection is not enough on
    its own either: build_role_prompts collapses every projected value except
    run_id and requirement to "present"/"absent", so the code has to be rendered
    for the Developer to repair instead of rewrite.
    """
    authored = "def autenticar(conexion, email, password):\n    return verificar(password)\n"
    state = EngineeringState(
        run_id="prompt",
        requirement="add password recovery",
        implementation=ImplementationResult(
            action_mode=ActionMode.PROPOSED,
            changed_files=["banca/auth.py"],
            diff="--- a/banca/auth.py\n+++ b/banca/auth.py\n+def recuperar(): ...",
            evidence=["banca/auth.py"],
            validation_result="pytest: 1 failed",
            file_contents={"banca/auth.py": authored},
        ),
        remediation_request="failed tests require implementation remediation",
        review=ReviewerDecision(
            status=ReviewerStatus.REJECTED, score=40, subscores={"testing": 0},
            reason="failed tests require implementation remediation", confidence=1,
            return_to=RouteTarget.DEVELOPER,
            problems=["ImportError: cannot import name 'encriptar_password'"],
        ),
    )
    envelope = build_context(AgentRole.DEVELOPER, state, "remediate")

    _, user = build_role_prompts(
        AgentRole.DEVELOPER, envelope, {}, {"action_mode": "PROPOSED"}
    )

    assert authored in user, "the Developer cannot repair code it cannot see"
    assert "banca/auth.py" in user


def test_only_the_developer_is_shown_previously_authored_code():
    """Security and Reviewer read evidence, not the author's draft."""
    authored = "SECRET_MARKER_ONLY_THE_AUTHOR_SEES = 1\n"
    state = EngineeringState(
        run_id="prompt",
        requirement="change",
        implementation=ImplementationResult(
            action_mode=ActionMode.PROPOSED,
            changed_files=["a.py"],
            diff="--- a/a.py\n+++ b/a.py\n+x = 1",
            evidence=["a.py"],
            validation_result="ok",
            file_contents={"a.py": authored},
        ),
    )
    for role in (AgentRole.SECURITY, AgentRole.REVIEWER):
        envelope = build_context(role, state, role.value)
        _, user = build_role_prompts(role, envelope, {}, {"action_mode": "PROPOSED"})
        assert authored not in user, f"{role.value} was shown the author's draft"


def _architecture_envelope(files: dict[str, str]) -> "object":
    state = EngineeringState(
        run_id="arch",
        requirement="map the authentication surface",
        tool_results=[
            ToolResult(
                tool_name="read_file", allowed_role=AgentRole.ARCHITECTURE,
                status=ToolStatus.SUCCESS, input_summary=f"path={path}",
                output_summary=content, duration_ms=0,
            )
            for path, content in files.items()
        ],
    )
    return build_context(AgentRole.ARCHITECTURE, state, "design")


def test_architecture_sees_every_small_file_that_fits_the_budget():
    """Finding 8: the cap was a file count, so file size did not matter.

    Twenty 500-byte files are 10 KB against a 16 KB budget and should all be
    shown. Under a fixed count of four, sixteen of them were dropped while the
    budget sat mostly unspent.
    """
    files = {
        f"src/mod{i:02d}.py": f"MARKER_MODULE_{i:02d}\n" + "x = 1\n" * 70
        for i in range(20)
    }
    _, user = build_role_prompts(
        AgentRole.ARCHITECTURE, _architecture_envelope(files), {}, {}
    )

    # The path of every read is listed either way; what matters is whose content
    # actually arrived.
    shown = [i for i in range(20) if f"MARKER_MODULE_{i:02d}" in user]
    assert len(shown) > 4, f"only {len(shown)} of 20 small files had content shown"


def test_architecture_is_told_what_it_was_not_shown():
    """A truncation the agent cannot see is a truncation it cannot report.

    This is finding 1's failure moved to the input: without knowing evidence was
    withheld, a design built on part of the repository is presented with the same
    confidence as one built on all of it.
    """
    files = {f"src/big{i:02d}.py": "# padding\n" + "y = 2\n" * 4000 for i in range(12)}
    _, user = build_role_prompts(
        AgentRole.ARCHITECTURE, _architecture_envelope(files), {}, {}
    )

    assert "omitted" in user.lower(), "the prompt never admits evidence was withheld"


def test_escape_heavy_evidence_still_respects_the_budget():
    """Escaping a newline costs two characters, so raw bytes are not the payload.

    A file of pure line breaks nearly doubles when serialized. The allocator
    renders, measures and shrinks rather than reserving for this worst case, and
    this is what proves the shrink actually converges.
    """
    files = {f"src/nl{i:02d}.py": f"MARKER_{i:02d}\n" + "\n" * 3000 for i in range(30)}
    _, user = build_role_prompts(
        AgentRole.ARCHITECTURE, _architecture_envelope(files), {}, {}
    )

    start = user.index('{"kind": "repository"')
    end = user.index("\nEvidence budget")
    payload = len(user[start:end].encode("utf-8"))
    assert payload <= 16 * 1024, f"serialized payload was {payload} bytes"
    assert "omitted" in user.lower()
