"""Contracts for the active documentation map and the preserved archive."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "docs/deprecated"
OWNERS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".github/copilot-instructions.md",
    "docs/README.md",
    "docs/architecture/overview.md",
    "docs/operations.md",
    "docs/testing.md",
    "docs/status.md",
    "docs/history.md",
)
# Accepted decisions are active documentation with one page per record, not a single
# owner file. The index is their entry point; the records themselves are immutable.
DECISIONS = "docs/architecture/decisions"
DECISION_INDEX = f"{DECISIONS}/README.md"
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\s]+)\)")


def _decision_records() -> set[str]:
    directory = ROOT / DECISIONS
    return {
        p.relative_to(ROOT).as_posix()
        for p in directory.glob("*.md")
        if p.name != "README.md"
    }


def _active_pages() -> set[str]:
    return set(OWNERS) | {DECISION_INDEX} | _decision_records()


def _manifest() -> dict:
    return json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))


def _specify_manifest() -> dict:
    return json.loads((ARCHIVE / "specify-manifest.json").read_text(encoding="utf-8"))


def _local_links(path: Path) -> list[Path]:
    # The active map uses inline Markdown links; archived Markdown is untrusted history.
    links = []
    for target in LINK.findall(path.read_text(encoding="utf-8")):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        links.append((path.parent / unquote(parsed.path)).resolve())
    return links


def test_active_owners_exist_and_are_reachable_from_entrypoints() -> None:
    owners = {ROOT / name for name in OWNERS} | {ROOT / DECISION_INDEX}
    assert all(path.is_file() for path in owners)
    visited = set()
    pending = [ROOT / "README.md"]
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        pending.extend(link for link in _local_links(path) if link in owners)
    # Harness adapters point into the map; they need not be linked by the product README.
    adapters = {ROOT / "CLAUDE.md", ROOT / ".github/copilot-instructions.md"}
    assert owners - adapters <= visited
    for adapter in adapters:
        assert ROOT / "AGENTS.md" in _local_links(adapter)


def test_active_local_links_resolve_without_loading_archived_pages() -> None:
    failures = []
    for name in sorted(_active_pages()):
        for target in _local_links(ROOT / name):
            if not target.is_relative_to(ROOT) or not target.exists():
                failures.append(f"{name}: missing or external local target {target}")
            allowed_archive_metadata = {
                ARCHIVE / "README.md", ARCHIVE / "manifest.json", ARCHIVE / "specify-manifest.json",
            }
            if target.is_relative_to(ARCHIVE) and target not in allowed_archive_metadata:
                failures.append(f"{name}: links directly into historical content")
    assert not failures, "\n".join(failures)


def test_active_documentation_has_no_unmapped_pages() -> None:
    active = {p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md")
              if not p.is_relative_to(ARCHIVE)}
    assert active == {name for name in _active_pages() if name.startswith("docs/")}


def test_every_decision_record_is_listed_by_its_index() -> None:
    index = ROOT / DECISION_INDEX
    linked = {
        link.relative_to(ROOT).as_posix()
        for link in _local_links(index)
        if link.is_relative_to(ROOT / DECISIONS)
    }
    records = _decision_records()
    assert records, "the decisions directory holds the accepted records"
    assert records == linked, "a record exists that the index does not list, or vice versa"


def test_archive_preserves_original_bytes_and_has_no_unrecorded_files() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == 1
    entries = manifest["archived"]
    assert entries
    sources = [entry["source"] for entry in entries]
    destinations = [entry["destination"] for entry in entries]
    assert len(sources) == len(set(sources))
    assert len(destinations) == len(set(destinations))
    for entry in entries:
        source = Path(entry["source"])
        assert not source.is_absolute() and ".." not in source.parts
        # Reserve the archive's README for its non-authoritative entry notice.
        relative = "root/README.md" if source.as_posix() == "README.md" else source.as_posix()
        assert entry["destination"] == f"docs/deprecated/{relative}"
        archived = ROOT / entry["destination"]
        assert archived.is_file(), entry["destination"]
        assert hashlib.sha256(archived.read_bytes()).hexdigest() == entry["sha256"]
        if replacement := entry.get("replacement"):
            runtime_paths = {resource["path"] for resource in manifest["retained"]}
            assert replacement in OWNERS or replacement in runtime_paths
            assert (ROOT / replacement).is_file()
        else:
            assert not (ROOT / source).exists(), f"retired path recreated: {source}"
    actual = {p.relative_to(ROOT).as_posix() for p in ARCHIVE.rglob("*") if p.is_file()}
    expected = set(destinations) | {
        "docs/deprecated/README.md", "docs/deprecated/manifest.json",
        "docs/deprecated/specify-manifest.json",
    } | {entry["destination"] for entry in _specify_manifest()["archived"]}
    assert actual == expected


def test_archived_speckit_installation_is_complete() -> None:
    manifest = _specify_manifest()
    entries = manifest["archived"]
    assert entries
    for entry in entries:
        source = Path(entry["source"])
        archived = ROOT / entry["destination"]
        assert source.parts[0] == ".specify"
        assert archived.is_file(), entry["destination"]
        assert hashlib.sha256(archived.read_bytes()).hexdigest() == entry["sha256"]
        assert not (ROOT / source).exists(), f"SpecKit path recreated: {source}"


def test_runtime_markdown_remains_outside_the_archive() -> None:
    # Hashes in the manifest are the migration baseline. Later authorized prompt/corpus
    # edits are allowed; their behavior is covered by runtime tests, not frozen here.
    entries = _manifest()["retained"]
    paths = [entry["path"] for entry in entries]
    assert len(paths) == len(set(paths))
    assert {entry["role"] for entry in entries} == {
        "runtime-system-prompt", "unresolved-user-prompt", "rag-input", "benchmark-input",
        "demo-case-input",
    }
    for name in paths:
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and not path.is_relative_to(ARCHIVE)
        assert path.is_file(), name
