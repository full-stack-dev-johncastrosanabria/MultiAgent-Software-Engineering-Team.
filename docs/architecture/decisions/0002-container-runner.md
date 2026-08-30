# 2. Execute target-project commands in a container, not a process sandbox

Date: 2026-08-30
Status: accepted
Supersedes the direction of: finding 3 in `docs/evidence/agent-architecture-audit.json`

## Context

Target-project commands currently run under an OS process sandbox: `sandbox-exec`
on Darwin, Bubblewrap on Linux, and a refusal everywhere else. Getting that far
took roughly 1,400 lines in `mcp/quality.py` and several rounds of security
review, and it is still not closed. Two findings remain open:

- a double-fork during the install phase escapes the 50 ms `ps` descendant
  monitor;
- historical PIDs are signalled without verifying identity, so PID reuse can
  deliver a signal to an unrelated process.

Both are races inherent to supervising processes that share the host kernel's
namespace from userspace. Closing them means writing more supervision, and each
round has produced a new gap rather than a proof.

The sandbox is also per-platform by construction. Windows has no third
implementation, so it fails closed — the system does not run there at all.

Finally, ADR 1 requires compiling native code and provisioning non-Python
toolchains. A process sandbox can restrict what a compiler touches, but it cannot
supply the compiler.

## Decision

Replace the per-platform process sandbox with a container runner. Target-project
commands execute inside a container image that carries the toolchain for the
project's stack.

The runner is an interface, not a single implementation. Docker is the first
backend because it is what developers already have. A microVM backend
(Firecracker or equivalent) is the intended second, for workloads that need a
stronger boundary than a shared kernel.

The process sandbox is not deleted on the day the container runner lands. It
remains the fallback for environments without a container runtime, and it is the
implementation the runner interface is first extracted around.

## Consequences

The two open races in finding 3 dissolve rather than being fixed. Descendant
processes and PID identity stop being this system's problem: the container's
lifecycle bounds them, and killing the container kills everything inside it.

Windows becomes supported, because Docker Desktop is the same interface there.
The current fail-closed refusal is therefore a temporary stance, not a policy.

Toolchain provisioning becomes image selection. A .NET project gets a .NET image;
a Java project gets a JDK image. This is what makes ADR 1 tractable.

The cost is a new dependency on a container runtime, slower cold starts than a
process fork, and image management — size, caching, and provenance of the base
images. Image provenance in particular is now a supply-chain surface that did not
exist before, and must be pinned by digest.

Agents gain room to be wrong. A destructive command inside a container damages a
container; the same command under a process sandbox damages whatever the sandbox
failed to anticipate.
