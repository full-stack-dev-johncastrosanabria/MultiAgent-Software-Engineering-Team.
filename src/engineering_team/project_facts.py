"""What the project declares about its own stack, stated to the Developer.

Models write code against the framework they were trained on. On 2026-09-16 the
authors of spring-demo read a pom declaring Spring Boot 4.0.5 and still wrote
Spring Boot 3 tests, five iterations in a row. The version was in the prompt as
raw XML; nothing said what it meant. This module states the declared versions,
the imports the project's own tests already rely on, and, for stacks where a
real classpath was probed, which familiar test APIs do not exist there.

Everything here is derived from repository files and bounded. Notes about a
framework are emitted only for the configuration they were verified against.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import PurePosixPath

import tomllib

_MAX_BYTES = 4096
_MAX_DEPENDENCIES = 25
_MAX_IMPORTS = 25

# Probed on spring-demo's real test classpath (Spring Boot 4.0.5 parent with
# spring-boot-starter-test): Class.forName reported these absent and present.
_SPRING_BOOT_4_MOCKS = (
    "Spring Boot 4: @MockBean (org.springframework.boot.test.mock.mockito) does not "
    "exist; @MockitoBean (org.springframework.test.context.bean.override.mockito) does."
)
_SPRING_BOOT_4_WEB_TESTS = (
    "With spring-boot-starter-test and no web test module, @WebMvcTest, "
    "@AutoConfigureMockMvc and TestRestTemplate are not on the classpath; use "
    "MockMvcBuilders.standaloneSetup (org.springframework.test.web.servlet.setup), "
    "Mockito and AssertJ are; so is RestTestClient (org.springframework.test.web.servlet.client)."
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _maven(path: str, text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    lines: list[str] = []
    parent_version = ""
    for element in root:
        name = _local(element.tag)
        if name == "parent":
            parent_version = _child(element, "version")
            lines.append(f"{path}: parent {_child(element, 'groupId')}:"
                         f"{_child(element, 'artifactId')} {parent_version}")
        elif name == "properties":
            properties = [
                f"{_local(item.tag)} {(item.text or '').strip()}" for item in element
                if _local(item.tag).endswith(("java.version", "kotlin.version", ".version"))
            ][:6]
            if properties:
                lines.append(f"{path}: properties " + ", ".join(properties))
    artifacts: list[str] = []
    for element in root.iter():
        if _local(element.tag) != "dependency":
            continue
        artifact = _child(element, "artifactId")
        if not artifact:
            continue
        version = _child(element, "version")
        scope = _child(element, "scope")
        artifacts.append(artifact + (f" {version}" if version else "") + (f" ({scope})" if scope else ""))
    if artifacts:
        lines.append(f"{path}: dependencies " + ", ".join(artifacts[:_MAX_DEPENDENCIES]))
    parent = next((line for line in lines if "spring-boot-starter-parent" in line), "")
    major = re.match(r"(\d+)", parent_version)
    if parent and major and int(major.group(1)) >= 4:
        lines.append(_SPRING_BOOT_4_MOCKS)
        declared = " ".join(artifacts)
        if "webmvc-test" not in declared and "resttestclient" not in declared:
            lines.append(_SPRING_BOOT_4_WEB_TESTS)
    return lines


def _dotnet(path: str, text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    frameworks = [
        (element.text or "").strip() for element in root.iter()
        if _local(element.tag) in {"TargetFramework", "TargetFrameworks"}
    ]
    packages = [
        f"{element.get('Include')} {element.get('Version') or ''}".strip()
        for element in root.iter()
        if _local(element.tag) == "PackageReference" and element.get("Include")
    ]
    lines = [f"{path}: target {', '.join(frameworks)}"] if frameworks else []
    if packages:
        lines.append(f"{path}: packages " + ", ".join(packages[:_MAX_DEPENDENCIES]))
    return lines


def _node(path: str, text: str) -> list[str]:
    try:
        manifest = json.loads(text)
    except ValueError:
        return []
    if not isinstance(manifest, dict):
        return []
    entries: list[str] = []
    for section, suffix in (("dependencies", ""), ("devDependencies", " (dev)")):
        block = manifest.get(section)
        if isinstance(block, dict):
            entries.extend(f"{name} {version}{suffix}" for name, version in block.items()
                           if isinstance(name, str) and isinstance(version, str))
    return [f"{path}: dependencies " + ", ".join(entries[:_MAX_DEPENDENCIES])] if entries else []


def _python(path: str, text: str) -> list[str]:
    pins = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith(("#", "-"))
    ]
    return [f"{path}: requirements " + ", ".join(pins[:_MAX_DEPENDENCIES])] if pins else []


def _pyproject(path: str, text: str) -> list[str]:
    try:
        project = tomllib.loads(text).get("project", {})
    except (tomllib.TOMLDecodeError, AttributeError):
        return []
    dependencies = project.get("dependencies") if isinstance(project, dict) else None
    if not isinstance(dependencies, list):
        return []
    pins = [item for item in dependencies if isinstance(item, str)]
    return [f"{path}: dependencies " + ", ".join(pins[:_MAX_DEPENDENCIES])] if pins else []


_IMPORT = re.compile(
    r"^\s*(?:import\s+(?:static\s+)?[\w.*]+|from\s+[\w.]+\s+import\s+[\w., ]+"
    r"|using\s+[\w.]+|import\s+[^;\n]+\s+from\s+['\"][^'\"]+['\"])\s*;?\s*$",
    re.MULTILINE,
)


def project_facts(manifests: Mapping[str, str], *, original_tests: Mapping[str, str]) -> str:
    lines: list[str] = []
    for path, text in sorted(manifests.items()):
        name = PurePosixPath(path).name
        if name == "pom.xml":
            lines.extend(_maven(path, text))
        elif name.endswith((".csproj", ".fsproj", ".vbproj")):
            lines.extend(_dotnet(path, text))
        elif name == "package.json":
            lines.extend(_node(path, text))
        elif name == "requirements.txt":
            lines.extend(_python(path, text))
        elif name == "pyproject.toml":
            lines.extend(_pyproject(path, text))
    imports = list(dict.fromkeys(
        match.group().strip().rstrip(";").removeprefix("import ").strip()
        if match.group().strip().startswith("import ") and " from " not in match.group()
        else match.group().strip().rstrip(";")
        for text in original_tests.values() for match in _IMPORT.finditer(text)
    ))[:_MAX_IMPORTS]
    if imports:
        lines.append("Imports the project's original tests already use: " + "; ".join(imports))
    if not lines:
        return ""
    block = (
        "PROJECT FACTS (derived from this repository's manifests and original tests; "
        "they override general knowledge of these frameworks):\n- " + "\n- ".join(lines)
        + "\n- Use only APIs these declared dependencies provide."
    )
    encoded = block.encode()
    return block if len(encoded) <= _MAX_BYTES else encoded[:_MAX_BYTES].decode(errors="ignore")
