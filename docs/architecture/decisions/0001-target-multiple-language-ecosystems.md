# 1. Target multiple language ecosystems

Date: 2026-08-30
Status: accepted

## Context

Every execution path in this system assumes Python. `QualityMCP` builds a Python
virtual environment, installs with pip, lints with ruff, and tests with pytest.
The demo projects are Python. The evidence gates read pytest output.

That assumption is not the product. The system reviews and modifies *target
projects*, and the projects worth reviewing are written in C#/.NET, Java with
Spring Boot, and TypeScript with React, Angular or Vue; they talk to SQL Server
and Postgres; they ship in Docker. A reviewer that only understands Python
cannot be pointed at them.

Even inside Python the assumption is too narrow. Installing PyTorch, NumPy, or a
database driver means compiling C, C++ or Rust. The current environment refuses
that class of work rather than supporting it.

## Decision

Multi-language support is a goal of the system, not a later extension. Every
structural decision about execution is made against that goal first.

The initial set: Python, C#/.NET, Java/Spring Boot, and the JavaScript and
TypeScript front-end stacks. Database targets: SQL Server and Postgres. Docker
is both a target the system must understand and, per ADR 2, the mechanism it
runs on.

## Consequences

A toolchain cannot be assumed present on the operator's machine — pytest, dotnet,
maven and npm will not all be installed, and requiring them would make the system
unusable. Toolchains must be provisioned per project, which is what ADR 2 does.

"Quality" stops meaning "pytest and ruff passed". It becomes a per-stack question
answered by a per-stack command set, which is what ADR 3 separates out.

Compilation of native code becomes a supported operation rather than a failure
mode, and that requires a real isolation boundary rather than a process sandbox.
