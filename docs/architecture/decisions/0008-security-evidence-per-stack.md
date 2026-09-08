# 8. Security evidence belongs to the component toolchain

Date: 2026-09-01
Status: accepted
Refines: [ADR 3](0003-split-quality-mcp.md), [ADR 4](0004-profile-per-component.md)

## Context

ADR 3 moved install, lint, test and build commands into a stack profile. ADR 4
attached that profile to a component. The Security tools were left behind:
`scan_dependencies` always prepared a Python virtual environment and ran
`pip check`, while `run_security_scan` always installed and ran `ruff`.

The first real JVM run exposed the contradiction. The selected Maven image was
correct and the run reached Security, then both tools tried to create a Python
virtual environment in that image. Maven images do not promise Python and the
container correctly refused. Reporting that as a target-project security
failure would be false; silently skipping it would be worse.

## Decision

Dependency integrity and security scanning are phases of `StackProfile`, beside
install, lint, test and build. Quality remains stack-agnostic: it asks the
profile for the command, executes it through the configured runner, and turns
its real exit status into component-scoped `ToolResult` evidence.

The initial profile operations are:

| Stack | Dependency integrity | Security evidence |
| --- | --- | --- |
| Python | install declared dependencies, then `pip check` | `ruff check --select S` over application source |
| JVM | Maven `dependency:tree` using the run cache | a version-pinned OWASP Dependency-Check Maven goal |
| Node | `npm ls --all` after the locked install | `npm audit --omit=dev --audit-level=high` |
| .NET | `dotnet list package --include-transitive` | `dotnet list package --vulnerable --include-transitive` with deterministic vulnerable-output handling |
| Go | `go list -m all` | a version-pinned `govulncheck` invocation |

The JVM profile reads NVD data from the public mirror maintained by
`dependency-check/DependencyCheck_Builder`. Direct NVD API downloads require a
key as of 2026; an absent key or unavailable mirror is a tooling failure, never
a successful scan.

An operation that needs a registry or advisory database declares network access
in its profile and remains bounded by the existing Quality timeout. A missing
command, unavailable advisory service, scanner error, or detected policy-level
finding does not become success: the `ToolResult` fails or is unavailable and
the deterministic Security/Reviewer gates block approval.

Python keeps its existing preparation path because its scanner is part of the
locked ASET quality toolchain. Non-Python profiles do not provision Python.

## Alternatives rejected

**Install Python in every component image.** This makes the symptom disappear
while retaining the wrong abstraction. It also expands every trusted image and
still gives `ruff` no meaningful Java, C#, JavaScript, or Go coverage.

**Use one generic scanner image for every operation.** A cross-language scanner
can be added later, but it does not replace ecosystem integrity commands and
would introduce a second runner/image lifecycle before evidence shows that is
needed. The component toolchain already resolves the exact graph being built.

**Return success when a profile has no scanner.** A skipped security control is
not successful evidence. This would let Reviewer approve precisely because the
required tool did not run.

**Let Security choose a command.** Tool selection affects approval and therefore
cannot depend on model text. Profiles and deterministic code choose it.

## Consequences

`StackProfile` gains dependency and security phases plus their network policy.
QualityMCP no longer contains a Python fallback for non-Python Security tools.
Tests must prove each supported profile declares both phases, unknown/missing
phases fail closed, and a real JVM container reaches Maven rather than Python.

The scanners measure different ecosystem-native signals; they are not claimed
to be semantically identical. Security still evaluates the complete checklist
from the Spec, while these tools provide concrete dependency/static evidence.
Their exact versions and output interpretation are implementation details that
must remain pinned and tested.
