# 4. A profile describes a component, not a repository

Date: 2026-08-30
Status: accepted
Refines: [ADR 3](0003-split-quality-mcp.md)

## Context

ADR 3 separated *which commands to run* into a stack profile, and left open what
a profile is attached to. The obvious answer is the repository: one project, one
stack, one set of commands.

Six real repositories were reviewed to check that. **None of them is a single
stack.** Every one is a backend and a frontend in the same repository —
Java 21 with Angular, C# with Vue, Flask with a TypeScript client — and
BusinessAI-Analytics is Java across seven Maven services *and* a Python FastAPI
service *and* a React frontend. InterviewCleanApi ships three separate frontend
clients.

A profile per repository does not describe any of them. It would have to pick one
stack and be wrong about the rest.

## Decision

A profile describes a **component**: a directory that carries a build manifest.
`pom.xml` or `build.gradle` means a JVM component, `*.csproj` a .NET one,
`package.json` a Node one, `requirements.txt` or `pyproject.toml` a Python one.
A repository has as many components as it has manifests, and a run works with all
of them.

Detection is the existence of a file. Nothing else.

## Alternatives rejected

**Ask the Architecture agent which stack this is.** It already reads the
repository and could answer in one sentence. This is rejected because it would
make a routing decision depend on free text from a model, which is the one
invariant the whole design rests on: Pydantic validates, routers decide, and the
gates read evidence. A wrong answer here silently selects the wrong toolchain and
every downstream result inherits it.

**Require the target repository to declare its components.** Explicit and
unambiguous, and it contradicts the premise. The system is pointed at projects
that already exist and whose repositories we do not control; needing a file in
each one means it only works on projects that have already adopted it.

**Infer from the language statistics GitHub reports.** Convenient, but it
describes byte counts and not buildable units. It says BusinessAI-Analytics is
"Java 872k, Python 694k, TypeScript 658k", which is true and tells you nothing
about where to run `mvn test`.

## Consequences

Several profiles are active in one run, so results are per component and the
evidence layer has to carry that. A run over BusinessAI-Analytics produces
results for nine components, and reporting one aggregate would hide which of them
failed.

The Python assumption currently living in about eight lines of `mcp/quality.py`
becomes one profile among several rather than the default everything else is
measured against.

Component detection is cheap and total, which makes it a better repository
summary than what Architecture reads today. That is a hint about
[finding 8](../findings/README.md), not a fix for it.

A directory with a manifest is not always a component worth building — vendored
dependencies and example directories also carry manifests. Detection needs the
same exclusion discipline the repository listing already learned in
[finding 4](../findings/README.md).
