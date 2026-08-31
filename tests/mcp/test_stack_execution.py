"""Each profile, run against a real component in a real container.

Gated on the images being present locally, so a machine without them still gets a
green suite. These are slow: they resolve dependencies over the network on the
first run, which is the behaviour `test_needs_network` declares.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.mcp.container import ContainerRunner
from engineering_team.mcp.quality import QualityMCP
from engineering_team.stacks import profile_for

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>probe</groupId><artifactId>probe</artifactId><version>1.0</version>
  <properties><maven.compiler.release>21</maven.compiler.release></properties>
  <dependencies><dependency><groupId>org.junit.jupiter</groupId>
    <artifactId>junit-jupiter</artifactId><version>5.10.2</version>
    <scope>test</scope></dependency></dependencies>
</project>
"""
JAVA_TEST = """import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class ProbeTest { @Test void suma() { assertEquals(2, 1 + 1); } }
"""
CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
  </ItemGroup>
</Project>
"""
CSHARP_TEST = """using Xunit;
public class ProbeTests { [Fact] public void Suma() { Assert.Equal(2, 1 + 1); } }
"""


def _image_present(reference: str) -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(
        ["docker", "image", "inspect", reference], capture_output=True, check=False
    ).returncode == 0


def _needs(stack: str):
    return pytest.mark.skipif(
        not _image_present(profile_for(stack).image),
        reason=f"pull the {stack} profile image to run this",
    )


def _run_tests(workspace: Path, stack: str) -> tuple[ToolStatus, str]:
    profile = profile_for(stack)
    runner = ContainerRunner(workspace, image=profile.image)
    quality = QualityMCP(workspace, timeout_seconds=900, runner=runner, profile=profile)
    try:
        result = quality.run_tests(AgentRole.TESTING)
        return result.status, result.output_summary
    finally:
        quality.close()


@_needs("jvm")
def test_a_maven_component_really_runs_its_tests(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text(POM, encoding="utf-8")
    java = tmp_path / "src" / "test" / "java"
    java.mkdir(parents=True)
    (java / "ProbeTest.java").write_text(JAVA_TEST, encoding="utf-8")

    status, output = _run_tests(tmp_path, "jvm")
    assert status is ToolStatus.SUCCESS, output[-1500:]


@_needs("node")
def test_a_node_component_really_runs_its_tests(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({
            "name": "probe", "version": "1.0.0", "private": True,
            "scripts": {"test": "node --test"},
        }),
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "name": "probe", "version": "1.0.0", "lockfileVersion": 3,
            "requires": True,
            "packages": {"": {"name": "probe", "version": "1.0.0"}},
        }),
        encoding="utf-8",
    )
    (tmp_path / "probe.test.js").write_text(
        "const t = require('node:test');\n"
        "const a = require('node:assert');\n"
        "t.test('suma', () => a.strictEqual(1 + 1, 2));\n",
        encoding="utf-8",
    )

    status, output = _run_tests(tmp_path, "node")
    assert status is ToolStatus.SUCCESS, output[-1500:]


@_needs("dotnet")
def test_a_dotnet_component_really_runs_its_tests(tmp_path: Path) -> None:
    (tmp_path / "Probe.csproj").write_text(CSPROJ, encoding="utf-8")
    (tmp_path / "ProbeTests.cs").write_text(CSHARP_TEST, encoding="utf-8")

    status, output = _run_tests(tmp_path, "dotnet")
    assert status is ToolStatus.SUCCESS, output[-1500:]
