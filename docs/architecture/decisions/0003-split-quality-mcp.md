# 3. Split QualityMCP into quality, runner, and stack profile

Date: 2026-08-30
Status: accepted

## Context

`mcp/quality.py` is 1,447 lines and answers three unrelated questions at once:

- **What is quality?** Which checks must pass, what counts as evidence, how a
  result is reported to the Testing and Reviewer gates.
- **Where does the code execute?** Ephemeral virtual environment, PATH
  construction, `sandbox-exec` and Bubblewrap policy, process supervision,
  timeouts.
- **With which commands?** `pip install`, `pytest`, `ruff check`, `compileall` —
  and the flags and configuration scoping each one needs.

Because the three are fused, a change to any one risks the others. Adding .NET
support (ADR 1) would mean editing the same file that holds the sandbox policy,
and swapping the sandbox for a container (ADR 2) would mean editing the same file
that defines what the evidence gates read.

## Decision

Separate the three along their own seams.

**Quality** stays the invariant: the definition of what must hold, and the
evidence contract that Testing and Reviewer consume. It does not know how
commands run.

**Runner** is where execution happens, behind an interface. Implementations: the
existing process sandbox, and the container backends from ADR 2. It knows how to
run a command and bound it; it does not know which commands matter.

**Stack profile** is the per-ecosystem command set — how to install, lint, test
and build for Python, .NET, Java, or a JS toolchain. It names commands; it does
not run them.

## Consequences

ADR 2 becomes an additive change: a new runner implementation alongside the
existing one, not a rewrite of the file that also defines quality.

ADR 1 becomes an additive change too: a new stack profile, with no exposure to
sandbox or container policy.

The evidence contract gets an explicit boundary, which it currently lacks. That
boundary is where a stack-agnostic definition of "tests ran and passed" has to be
written — today the gates read pytest's output shape directly.

The cost is indirection: three seams where there was one file, and a period where
the split is incomplete and both shapes exist.
