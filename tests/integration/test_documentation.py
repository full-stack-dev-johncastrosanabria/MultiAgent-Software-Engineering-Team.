from pathlib import Path


def test_required_documentation_and_demo_commands_are_present() -> None:
    required = [
        "README.md", "docs/architecture/overview.md", "docs/diagrams/architecture.md",
        "docs/diagrams/langgraph.md", "docs/rag.md", "docs/mcp.md",
        "docs/evaluation.md", "docs/demo-runbook.md",
        "docs/evidence/final-audit.md",
    ]
    for filename in required:
        assert Path(filename).is_file(), filename

    combined = "\n".join(Path(filename).read_text(encoding="utf-8") for filename in required)
    for phrase in (
        "Sentence Transformers", "Chroma", "NO_RELEVANT_DOCS", "run_tests",
        "HUMAN_REVIEW_REQUIRED", "qwen3.5:4b", "qwen3.5:9b", "LANGFUSE_PUBLIC_KEY",
        "SC-01", "SC-05", "scripts/run_evaluation.py", "scripts/run_multimodel.py",
        "LangChain Document", "MCP Server", "stdio", "--live-models",
        "scenarios-live.json",
    ):
        assert phrase in combined


def test_architecture_documentation_has_its_five_parts() -> None:
    """Each part answers a different question; a missing one means a homeless fact."""
    for filename in (
        "docs/architecture/README.md",
        "docs/architecture/overview.md",
        "docs/architecture/roadmap.md",
        "docs/architecture/decisions/README.md",
        "docs/architecture/checklists/README.md",
        "docs/architecture/findings/README.md",
        "docs/architecture/findings/agent-architecture-audit.json",
    ):
        assert Path(filename).is_file(), filename


def test_every_finding_in_the_audit_appears_in_the_index() -> None:
    """The JSON is the record; the index is how anyone finds out where it stands."""
    import json

    audit = json.loads(
        Path("docs/architecture/findings/agent-architecture-audit.json").read_text(
            encoding="utf-8"
        )
    )
    index = Path("docs/architecture/findings/README.md").read_text(encoding="utf-8")
    for number in range(1, len(audit["findings"]) + 1):
        assert f"| {number} |" in index, f"finding {number} is not in the index"


def test_nothing_still_points_at_the_moved_audit() -> None:
    """A link that survives a move is a link that lies."""
    stale = []
    for path in Path(".").rglob("*.md"):
        if any(part in {".venv", "node_modules", ".git"} for part in path.parts):
            continue
        if "docs/evidence/agent-architecture-audit" in path.read_text(encoding="utf-8"):
            stale.append(str(path))
    assert not stale, f"stale audit path in: {stale}"


def test_every_decision_record_appears_in_its_index() -> None:
    """An ADR nobody can find from the index is an ADR nobody reads."""
    directory = Path("docs/architecture/decisions")
    index = (directory / "README.md").read_text(encoding="utf-8")
    records = sorted(p.name for p in directory.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert records, "no decision records found"
    for name in records:
        assert name in index, f"{name} is not linked from the decisions index"
