"""Guard on the size of the Docker omission budget.

The count comes from tests/conftest.py's `pytest_collection_modifyitems` hook,
which is the public collection API, and reaches this test through the
`needs_docker_budget` fixture.
"""

# Measured, not predicted: these are exactly the tests that fail when the CLI
# is present and the daemon is unreachable. The research notes projected 21
# (.superpowers/fase1/research-test-gate.md §5.4); the one-line
# `require_available` patch in tests/mcp/test_quality.py turned out to fix 9
# tests rather than the 5 the notes expected, so 8 remain in that file.
EXPECTED_NEEDS_DOCKER_COUNT = 13

# Per file, so a run that deliberately collects only part of the suite (the
# repository's pinned regression command) still checks what it did collect
# instead of asserting a whole-suite total it never had a chance to see.
EXPECTED_NEEDS_DOCKER_BY_FILE = {
    "tests/mcp/test_quality.py": 8,
    "tests/mcp/test_protocol.py": 1,
    "tests/integration/test_workflow.py": 1,
    "tests/e2e/test_evaluation_scenarios.py": 3,
}


def test_needs_docker_mark_count_has_not_grown_or_shrunk_silently(
    needs_docker_budget: dict[str, object],
) -> None:
    """A new Docker-dependent test must add itself here on purpose, not by
    accident, and a test that stops needing Docker must remove its own mark
    -- this is what keeps 'omisiones explicadas' explained rather than a
    number nobody looks at."""

    assert sum(EXPECTED_NEEDS_DOCKER_BY_FILE.values()) == EXPECTED_NEEDS_DOCKER_COUNT

    marked: dict[str, int] = needs_docker_budget["marked_by_file"]  # type: ignore[assignment]
    collected: set[str] = needs_docker_budget["collected_files"]  # type: ignore[assignment]

    unexpected = sorted(path for path in marked if path not in EXPECTED_NEEDS_DOCKER_BY_FILE)
    assert not unexpected, (
        f"{unexpected} grew needs_docker marks without being declared here -- "
        f"add the file and its count deliberately, or make the test run without a daemon"
    )

    for path, expected in EXPECTED_NEEDS_DOCKER_BY_FILE.items():
        if path not in collected:
            continue
        assert marked.get(path, 0) == expected, (
            f"expected {expected} tests marked needs_docker in {path}, "
            f"found {marked.get(path, 0)} -- update this table deliberately if a "
            f"test genuinely started or stopped needing a daemon"
        )

    if EXPECTED_NEEDS_DOCKER_BY_FILE.keys() <= collected:
        assert sum(marked.values()) == EXPECTED_NEEDS_DOCKER_COUNT, (
            f"expected {EXPECTED_NEEDS_DOCKER_COUNT} tests marked needs_docker across "
            f"the suite, found {sum(marked.values())}"
        )
