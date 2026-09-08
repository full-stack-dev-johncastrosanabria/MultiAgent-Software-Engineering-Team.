"""Fresh JUnit/xUnit/TRX cases for deterministic Testing coverage.

Reports establish execution; an exact source method adds context to that case.
Neither source discovery nor a report left by a previous run establishes execution.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from engineering_team.contracts.models import ExecutedTestCase

_MAX_REPORT_BYTES = 4 * 1024 * 1024
_MAX_SOURCE_BYTES = 512 * 1024
_MAX_EXCERPT = 4000
_MAX_CASES = 2000
_EXCLUDED = {".git", ".venv", "node_modules", "bin", "obj"}
ReportSnapshot = dict[Path, tuple[int, int, int]]


def _within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def snapshot_reports(root: Path, stack: str) -> ReportSnapshot:
    """Only conventional report locations belonging to this component."""
    patterns = {
        "jvm": ("**/target/surefire-reports/TEST-*.xml", "**/target/failsafe-reports/TEST-*.xml"),
        "dotnet": ("**/TestResults/**/*.trx", "**/TestResults/**/*.xml"),
    }.get(stack, ())
    found: ReportSnapshot = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if not _within(path, root) or path.is_symlink():
                continue
            try:
                stat = path.stat()
                if path.is_file() and stat.st_size <= _MAX_REPORT_BYTES:
                    found[path] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
            except OSError:
                continue
    return found


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _passing_cases(root: ET.Element) -> list[tuple[str, str, str]]:
    """Return (display identity, class, method) only for explicit/implicit passes."""
    cases: list[tuple[str, str, str]] = []
    if _tag(root) == "TestRun":
        methods = {}
        for unit in root.iter():
            if _tag(unit) != "UnitTest":
                continue
            method = next((node for node in unit if _tag(node) == "TestMethod"), None)
            if method is not None:
                methods[unit.get("id")] = (
                    method.get("className", "").split(",", 1)[0], method.get("name", "")
                )
        for result in root.iter():
            if _tag(result) != "UnitTestResult" or result.get("outcome") != "Passed":
                continue
            class_name, method = methods.get(result.get("testId"), ("", ""))
            display = result.get("testName", "")
            if display:
                cases.append((display, class_name, method))
    elif _tag(root) in {"testsuite", "testsuites"}:
        for case in root.iter():
            if _tag(case) != "testcase":
                continue
            if any(_tag(child) in {"skipped", "failure", "error"} for child in case):
                continue
            if case.get("status", "run").lower() in {"notrun", "disabled", "skipped"}:
                continue
            if case.get("result", "completed").lower() in {"skipped", "suppressed", "failed"}:
                continue
            name, class_name = case.get("name", ""), case.get("classname", "")
            if name:
                method = re.split(r"[\[(]", name, maxsplit=1)[0]
                cases.append((f"{class_name}::{name}", class_name, method))
    elif _tag(root) in {"assemblies", "assembly"}:
        for case in root.iter():
            if _tag(case) == "test" and case.get("result") == "Pass":
                name = case.get("name", "")
                if name:
                    cases.append((name, case.get("type", ""), case.get("method", "")))
    return cases


def _masked_source(source: str) -> tuple[str, str]:
    """Mask comments and literals for delimiters; remove comments from excerpts.

    Supports Java text blocks and C# normal/verbatim/raw strings. Interpolated
    contents stay opaque: braces in string data never delimit a method.
    """
    pattern = re.compile(
        r'//[^\n]*|/\*[\s\S]*?\*/|"{3,}[\s\S]*?"{3,}'
        r'|@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    )
    masked, uncommented = list(source), list(source)
    for match in pattern.finditer(source):
        comment = match.group().startswith(("//", "/*"))
        for index in range(match.start(), match.end()):
            if source[index] != "\n":
                masked[index] = " "
                if comment:
                    uncommented[index] = " "
    return "".join(masked), "".join(uncommented)


def _method_excerpt(source: str, method: str) -> str:
    if not re.fullmatch(r"[A-Za-z_$][\w$]*", method):
        return ""
    masked, uncommented = _masked_source(source)
    # JUnit void and xUnit void/Task/ValueTask methods. Calls are not definitions.
    signature = re.compile(
        rf"\b(?:void|Task|ValueTask)(?:\s*<[^;{{}}]+>)?\s+{re.escape(method)}\s*\("
    )
    matches = list(signature.finditer(masked))
    if len(matches) != 1:
        return ""
    match = matches[0]
    cursor, depth = match.end(), 1
    while cursor < len(masked) and depth:
        depth += (masked[cursor] == "(") - (masked[cursor] == ")")
        cursor += 1
    # Java may declare checked exceptions; expression-bodied C# is unsupported.
    suffix = re.match(r"\s*(?:throws\s+[\w.,\s]+)?\{", masked[cursor:])
    if depth or suffix is None:
        return ""
    cursor += suffix.end()
    depth = 1
    while cursor < len(masked) and depth:
        depth += (masked[cursor] == "{") - (masked[cursor] == "}")
        cursor += 1
    if depth:
        return ""
    return uncommented[match.start():cursor][:_MAX_EXCERPT]


def _class_source(source: str, class_name: str) -> str:
    """Resolve the full declaring class and hide nested classes' methods."""
    masked, _ = _masked_source(source)
    namespace = re.search(r"\b(?:package|namespace)\s+([\w.]+)", masked)
    prefix = namespace.group(1) + "." if namespace else ""
    declarations: list[tuple[str, int, int]] = []
    for match in re.finditer(r"\bclass\s+(\w+)\b[^;{}]*\{", masked):
        cursor, depth = match.end(), 1
        while cursor < len(masked) and depth:
            depth += (masked[cursor] == "{") - (masked[cursor] == "}")
            cursor += 1
        if not depth:
            declarations.append((match.group(1), match.end(), cursor - 1))
    found: list[str] = []
    for name, start, end in declarations:
        parents = [n for n, a, b in declarations if a < start < end < b]
        qualified = prefix + ".".join([*parents, name])
        if qualified != class_name.replace("$", ".").replace("+", "."):
            continue
        body = list(source[start:end])
        for _, child_start, child_end in declarations:
            if start < child_start < child_end < end:
                body[child_start - start:child_end - start] = " " * (child_end - child_start)
        found.append("".join(body))
    return found[0] if len(found) == 1 else ""


def _source_excerpt(root: Path, stack: str, class_name: str, method: str) -> str:
    if not class_name or not method:
        return ""
    class_leaf = re.split(r"[.$+]", class_name)[-1]
    if not re.fullmatch(r"\w+", class_leaf):
        return ""
    extension = "java" if stack == "jvm" else "cs"
    matches: list[str] = []
    for path in root.rglob(f"*.{extension}"):
        if any(part in _EXCLUDED for part in path.relative_to(root).parts):
            continue
        if not _within(path, root) or path.is_symlink():
            continue
        try:
            if path.stat().st_size > _MAX_SOURCE_BYTES:
                continue
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        excerpt = _method_excerpt(_class_source(source, class_name), method)
        if excerpt:
            matches.append(f"{path.relative_to(root).as_posix()}:\n{excerpt}")
    return matches[0] if len(matches) == 1 else ""


def collect_test_cases(root: Path, stack: str, before: ReportSnapshot) -> list[ExecutedTestCase]:
    cases: list[ExecutedTestCase] = []
    excerpts: dict[tuple[str, str], str] = {}
    for path, signature in sorted(snapshot_reports(root, stack).items()):
        if before.get(path) == signature:
            continue
        try:
            document = path.read_bytes()
            # No DTD/entities are needed by test reports; fail closed on these.
            if b"<!DOCTYPE" in document or b"<!ENTITY" in document:
                continue
            report = ET.fromstring(document)
        except (OSError, ET.ParseError):
            continue
        for identifier, class_name, method in _passing_cases(report):
            key = (class_name, method)
            if key not in excerpts:
                excerpts[key] = _source_excerpt(root, stack, class_name, method)
            cases.append(ExecutedTestCase(
                identifier=identifier,
                report=path.relative_to(root).as_posix(),
                source_excerpt=excerpts[key],
            ))
            if len(cases) >= _MAX_CASES:
                return cases
    return cases
