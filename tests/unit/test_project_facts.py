"""The Developer is told the versions the project declares, not left to guess them."""

from engineering_team.project_facts import project_facts

SPRING_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>4.0.5</version>
  </parent>
  <properties><java.version>21</java.version></properties>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-webmvc</artifactId></dependency>
    <dependency><groupId>com.mysql</groupId><artifactId>mysql-connector-j</artifactId><scope>runtime</scope></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>
  </dependencies>
</project>
"""
SPRING_TEST = """package com.john.springdemo;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class SpringDemoApplicationTests { @Test void contextLoads() {} }
"""


def test_spring_boot_4_facts_name_the_version_and_the_verified_test_apis():
    """spring-demo, 2026-09-16: authors read this pom and still wrote @MockBean and
    @WebMvcTest, which a real probe of this classpath showed do not exist."""
    facts = project_facts(
        {"pom.xml": SPRING_POM},
        original_tests={"src/test/java/SpringDemoApplicationTests.java": SPRING_TEST},
    )
    assert "spring-boot-starter-parent 4.0.5" in facts
    assert "spring-boot-starter-test (test)" in facts
    assert "java.version 21" in facts
    assert "@MockBean" in facts and "@MockitoBean" in facts
    assert "@WebMvcTest" in facts and "MockMvcBuilders.standaloneSetup" in facts
    assert "org.springframework.boot.test.context.SpringBootTest" in facts


def test_a_declared_web_test_module_does_not_get_the_unavailable_claim():
    pom = SPRING_POM.replace("spring-boot-starter-test</artifactId>",
                             "spring-boot-starter-webmvc-test</artifactId>")
    facts = project_facts({"pom.xml": pom}, original_tests={})
    assert "@MockitoBean" in facts
    assert "@WebMvcTest" not in facts


def test_spring_boot_3_gets_no_boot_4_note():
    facts = project_facts({"pom.xml": SPRING_POM.replace("4.0.5", "3.3.2")}, original_tests={})
    assert "spring-boot-starter-parent 3.3.2" in facts
    assert "@MockitoBean" not in facts


def test_dotnet_node_and_python_manifests_are_summarised():
    facts = project_facts({
        "Api/Api.csproj": (
            '<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
            '</PropertyGroup><ItemGroup><PackageReference Include="Pomelo.EntityFrameworkCore.MySql" '
            'Version="9.0.0" /></ItemGroup></Project>'
        ),
        "web/package.json": '{"dependencies": {"react": "^19.1.0"}, "devDependencies": {"vitest": "3.2.0"}}',
        "requirements.txt": "Flask==3.0.0\n# comment\npytest>=8\n",
    }, original_tests={"tests/test_app.py": "import pytest\nfrom app import create_app\n"})
    assert "net10.0" in facts and "Pomelo.EntityFrameworkCore.MySql 9.0.0" in facts
    assert "react ^19.1.0" in facts and "vitest 3.2.0 (dev)" in facts
    assert "Flask==3.0.0" in facts and "pytest>=8" in facts
    assert "from app import create_app" in facts


def test_malformed_manifests_are_skipped_and_the_block_stays_bounded():
    facts = project_facts({
        "pom.xml": "<project><unclosed>",
        "package.json": "{not json",
        "requirements.txt": "\n".join(f"package{i}==1.0" for i in range(500)),
    }, original_tests={})
    assert len(facts.encode()) <= 4096


def test_nothing_known_yields_no_block():
    assert project_facts({}, original_tests={}) == ""


def test_pyproject_dependencies_are_summarised():
    facts = project_facts({"api/pyproject.toml": (
        "[project]\nname = 'example'\ndependencies = ['flask>=3.0', 'sqlalchemy==2.0.30']\n"
    )}, original_tests={})
    assert "flask>=3.0" in facts and "sqlalchemy==2.0.30" in facts


def test_the_developer_prompt_carries_the_facts():
    from engineering_team.contracts.enums import AgentRole
    from engineering_team.contracts.models import ImplementationResult
    from engineering_team.contracts.state import EngineeringState
    from engineering_team.llm.prompting import build_role_prompts
    from engineering_team.models.context import build_context

    envelope = build_context(AgentRole.DEVELOPER, EngineeringState(run_id="f", requirement="r"), "Developer")
    envelope = envelope.model_copy(update={"project_facts": "PROJECT FACTS (derived...):\n- pom.xml: parent x 4.0.5"})
    _, user = build_role_prompts(AgentRole.DEVELOPER, envelope, ImplementationResult, {})
    assert "pom.xml: parent x 4.0.5" in user
