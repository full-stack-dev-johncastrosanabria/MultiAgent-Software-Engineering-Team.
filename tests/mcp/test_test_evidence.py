"""Report evidence must prove execution and attribute only the matching method."""

from pathlib import Path

import pytest

from engineering_team.mcp.test_evidence import collect_test_cases, snapshot_reports


def _report(root: Path, text: str, stack: str = "jvm") -> Path:
    relative = (
        "target/surefire-reports/TEST-OrderTest.xml"
        if stack == "jvm" else "TestResults/run/results.trx"
    )
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _source(root: Path, source: str, name: str = "OrderTest.java") -> Path:
    path = root / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def test_junit_passes_only_fresh_reports_and_excludes_skips_errors_failures(tmp_path):
    old = _report(tmp_path, '<testsuite><testcase name="old"/></testsuite>')
    before = snapshot_reports(tmp_path, "jvm")
    assert collect_test_cases(tmp_path, "jvm", before) == []
    old.write_text('''<testsuite>
      <testcase classname="orders.OrderTest" name="permite[1]"/>
      <testcase name="skipped"><skipped/></testcase>
      <testcase name="failed"><failure/></testcase>
      <testcase name="error"><error/></testcase>
      <testcase name="disabled" status="notrun"/>
    </testsuite>''')
    _source(tmp_path, '''package orders;
      class OrderTest {
        void permite() { assertEquals(0, order.getMaximum()); }
        void vecino() { invalidPassword(); }
      }''')
    cases = collect_test_cases(tmp_path, "jvm", before)
    assert [case.identifier for case in cases] == ["orders.OrderTest::permite[1]"]
    assert cases[0].report == old.relative_to(tmp_path).as_posix()
    assert "getMaximum" in cases[0].source_excerpt
    assert "invalidPassword" not in cases[0].source_excerpt


def test_trx_pass_requires_result_and_definition_before_adding_source(tmp_path):
    _source(tmp_path, '''namespace Orders;
      public class OrderTest {
        public async Task Permite() { await BoundaryAsync(); }
        public void Vecino() { InvalidPassword(); }
      }''', "OrderTest.cs")
    _report(tmp_path, '''<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
      <Results>
        <UnitTestResult testId="1" testName="Permite(value: 0)" outcome="Passed"/>
        <UnitTestResult testId="2" testName="Vecino" outcome="NotExecuted"/>
        <UnitTestResult testId="3" testName="Unmapped" outcome="Passed"/>
        <UnitTestResult testId="4" testName="Failed" outcome="Failed"/>
      </Results>
      <TestDefinitions>
        <UnitTest id="1"><TestMethod className="Orders.OrderTest, Assembly" name="Permite"/></UnitTest>
        <UnitTest id="2"><TestMethod className="Orders.OrderTest" name="Vecino"/></UnitTest>
      </TestDefinitions>
    </TestRun>''', "dotnet")
    cases = collect_test_cases(tmp_path, "dotnet", {})
    assert [case.identifier for case in cases] == ["Permite(value: 0)", "Unmapped"]
    assert "BoundaryAsync" in cases[0].source_excerpt
    assert "InvalidPassword" not in cases[0].source_excerpt
    assert cases[1].source_excerpt == ""
    assert collect_test_cases(tmp_path, "dotnet", snapshot_reports(tmp_path, "dotnet")) == []


@pytest.mark.parametrize("source", [
    "package wrong; class OrderTest { void permite() { boundary(); } }",
    "package orders; class OtherTest { void permite() { boundary(); } }",
    "package orders; class OrderTest { void permite(int a) {} void permite() {} }",
    "package orders; class OrderTest { class Nested { void permite() {} } }",
])
def test_mismatch_and_ambiguous_methods_never_borrow_source(tmp_path, source):
    _source(tmp_path, source)
    _report(tmp_path, '<testsuite><testcase classname="orders.OrderTest" name="permite"/></testsuite>')
    cases = collect_test_cases(tmp_path, "jvm", {})
    assert len(cases) == 1
    assert cases[0].source_excerpt == ""


def test_duplicate_classes_do_not_pick_arbitrary_file(tmp_path):
    source = "package orders; class OrderTest { void permite() { boundary(); } }"
    _source(tmp_path, source)
    _source(tmp_path, source, "Duplicate.java")
    _report(tmp_path, '<testsuite><testcase classname="orders.OrderTest" name="permite"/></testsuite>')
    assert collect_test_cases(tmp_path, "jvm", {})[0].source_excerpt == ""


def test_braces_in_literals_and_comments_cannot_include_neighbor(tmp_path):
    _source(tmp_path, '''package orders;
      class OrderTest {
        void permite() {
          String a = "}";
          String b = """ { } """;
          char c = '}';
          /* } invalidPassword(); */
          assertEquals(0, order.getMaximum());
        }
        void vecino() { invalidPassword(); }
      }''')
    _report(tmp_path, '<testsuite><testcase classname="orders.OrderTest" name="permite"/></testsuite>')
    excerpt = collect_test_cases(tmp_path, "jvm", {})[0].source_excerpt
    assert "getMaximum" in excerpt
    assert "invalidPassword" not in excerpt


@pytest.mark.parametrize("text", [
    "<broken>",
    '<!DOCTYPE test [<!ENTITY fake "boundary">]><testsuite/>',
    '<testsuite><testcase name="skipped"><skipped/></testcase></testsuite>',
])
def test_unusable_report_produces_no_pass_evidence(tmp_path, text):
    _report(tmp_path, text)
    assert collect_test_cases(tmp_path, "jvm", {}) == []


def test_symlinked_report_outside_component_is_ignored(tmp_path):
    outside = tmp_path / "outside.xml"
    outside.write_text('<testsuite><testcase name="boundary"/></testsuite>')
    root = tmp_path / "component"
    path = _report(root, "<testsuite/>")
    path.unlink()
    path.symlink_to(outside)
    assert collect_test_cases(root, "jvm", {}) == []


def test_csharp_verbatim_and_raw_literals_do_not_break_method_bounds(tmp_path):
    _source(tmp_path, '''namespace Orders;
      class OrderTest {
        public void Permite() {
          var a = @"} "" {";
          var b = """ } { """;
          var c = $"{value} }}";
          // } InvalidPassword();
          Boundary();
        }
        public void Vecino() { InvalidPassword(); }
      }''', "OrderTest.cs")
    _report(tmp_path, '''<assemblies><assembly><collection>
      <test name="Orders.OrderTest.Permite" type="Orders.OrderTest"
            method="Permite" result="Pass"/>
      <test name="Orders.OrderTest.Vecino" type="Orders.OrderTest"
            method="Vecino" result="Skip"/>
    </collection></assembly></assemblies>''', "dotnet")
    cases = collect_test_cases(tmp_path, "dotnet", {})
    assert len(cases) == 1
    assert "Boundary();" in cases[0].source_excerpt
    assert "InvalidPassword" not in cases[0].source_excerpt


def test_oversized_source_is_ignored_and_excerpt_is_bounded(tmp_path):
    from engineering_team.mcp.test_evidence import _MAX_EXCERPT, _MAX_SOURCE_BYTES

    path = _source(tmp_path, "class OrderTest { void permite() {" + "x();" * 2000 + "} }")
    _report(tmp_path, '<testsuite><testcase classname="OrderTest" name="permite"/></testsuite>')
    excerpt = collect_test_cases(tmp_path, "jvm", {})[0].source_excerpt
    assert len(excerpt.split(":\n", 1)[1]) == _MAX_EXCERPT
    path.write_text(path.read_text() + " " * _MAX_SOURCE_BYTES)
    assert collect_test_cases(tmp_path, "jvm", {})[0].source_excerpt == ""
