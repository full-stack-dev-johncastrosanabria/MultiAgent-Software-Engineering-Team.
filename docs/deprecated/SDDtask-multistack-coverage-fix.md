# Multistack test evidence transport

Status: implementation complete; parent review and the next live ASET trial remain pending.

## Cause and change

Maven's quiet successful run supplied no stdout. Testing classified only stdout and the
component URI, so nine passing OrderTest cases failed to demonstrate boundary,
business_rule, error and validation dimensions to Reviewer.

Quality now snapshots conventional JUnit/TRX/xUnit report files immediately before the
runner and attaches only passing cases from new or changed reports after success.
The dotnet hook requests a TRX logger. Cached test results retain these cases.
`test_cases=None` preserves legacy evidence; an empty list explicitly provides no passing
case evidence, even if stdout contains coverage keywords or the exit code is zero.

Each case includes its report path and optional bounded source excerpt. An excerpt requires
an unambiguous full class and method match. Comments and literals cannot alter method brace
boundaries; mismatches, overload ambiguity, duplicate sources and skipped tests do not
borrow neighboring methods. Reports and source files have byte limits; reports outside the
component and symlink files are ignored. Testing reads the latest evidence per component,
so older iterations cannot restore missing coverage. No model or gate relaxation is added.

Source context supports deterministic category classification of the executed test; it does
not establish statement or branch coverage. Excerpts support Java void and C# void/Task/
ValueTask block methods. Unsupported syntax receives no excerpt.

## Validation

- Parser: 14 passing tests covering fresh/stale JUnit and TRX reports, skipped/failed cases,
  class mismatch, ambiguity, neighboring methods, Java/C# literals, xUnit XML, malformed
  XML, DTD rejection, symlinks and source/excerpt size limits.
- Testing: 8 passing tests, including quiet report evidence and latest-component evidence
  replacing old passing cases with an empty fresh result.
- Quality profile hooks: 13 passing tests, including JVM/.NET report collection, TRX logger,
  getter preservation and suppression of passing report cases when the command fails.
- Multi-component evidence: 9 passing tests. Reviewer evidence: 15 passing tests and one
  existing failure expecting the substring `write`. That failure was reproduced using
  an isolated `git archive HEAD src` baseline with the identical assertion failure.
- An expanded 116-test run completed with 110 passes, 5 failures and 1 skip before the
  final four additional regression cases. Besides the existing Reviewer failure, failures
  involved ProcessRunner pipe timing, quality-tool installation and two Python 3.14
  sandbox ensurepip timeouts. These runner/environment paths are outside this change.
- Ruff passes for all changed files except the two existing PYI034/UP037 findings in
  CompositeQuality.__enter__; both were confirmed on HEAD. `git diff --check` passes.

Read-only replay of the real order-ms report found 75 passing cases and resolved all nine
OrderTest methods. Those nine cases plus the exact ProductSpecification from trace
`apply-7f67441d-697a-4da2-b415-e6b6237a8462` produce nonempty happy_path, boundary,
business_rule, error and validation mappings to `quality://order-ms/run_tests`.
Evidence: `workspace/evaluation/multistack-20260905/evidence/ingresos-testing-replay.json`
in the main workspace. This is an existing-report replay, not a new suite execution;
freshness is separately verified by snapshot regressions. Target code was not modified.
