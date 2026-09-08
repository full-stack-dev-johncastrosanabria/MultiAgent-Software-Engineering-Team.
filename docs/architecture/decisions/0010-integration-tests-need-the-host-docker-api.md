# 10. Integration tests run under the process sandbox, not the container runner

Date: 2026-09-07. Status: accepted.

## Context

`order-ms` proves its behaviour against a real PostgreSQL and a real Kafka
through Testcontainers, which asks the Docker daemon for them while the suite
runs. Two of our backends could host that suite, and only one of them can.

Under the process sandbox the integration suite passes: trial 10 ran
`OrderFlowIntegrationTest` six of six in 11.6 seconds, inside a component whose
full suite was 78 tests with no failure and no error.

Under the container runner it cannot. Testcontainers inside the quality
container has no route to a Docker API and fails to pull `postgres:17-alpine`
(`ContainerFetchException`). The same shape appeared in trial 6b and again in
trial 9, where every other gate passed and `testing` alone scored zero.

The fix that would make it work is to expose the host's Docker socket to the
quality container. That was proposed during the series and refused: a container
holding the host socket can start any container it likes on the host, with the
host's privileges, which is the boundary ADR 2 exists to draw. Refusing it was
the right call and this record exists so it is not reopened by accident.

`ServiceStack` (ADR 5) is a different mechanism and does not substitute. It
starts what a project's Compose file declares, before the phases run; it does
not answer the API call a Testcontainers suite makes from inside a test.

## Decision

A component whose tests drive containers themselves runs under
`quality_runner=process`. The container runner stays the backend for suites that
do not, and for hosts where the process sandbox is unavailable.

We do not mount the host Docker socket into the quality container. A suite that
needs the daemon runs on a boundary that already has it.

## Consequences

The multistack benchmark selects the process runner for Ingresos, and any
future target whose suite uses Testcontainers or an equivalent. This is a
selection rule, not a defect to schedule: `fp-t9-testcontainers-no-docker-api`
describes a limit of one backend, not work in progress.

ADR 2 intended the container runner to replace the process sandbox. It cannot,
for this class of suite, until a container backend can offer a container API
that is not the host's — a nested runtime, or a daemon scoped to the run. Until
then the process sandbox is not a fallback but the supported path for these
components.

The process sandbox carries its own conditions, both measured during this
series and now enforced in code: it must grant the JVM's agent attachment
(`java_agents`, so Mockito's inline mock maker loads as a `-javaagent` instead
of attaching to itself) and it must let a toolchain's launcher fork
independently of whether the phase reaches the network (`needs_subprocesses`,
because `mvn` is a shell script).

## Accepted alongside this: the JDK is not pinned

`ProcessRunner` rebuilds the child's PATH and passes through a small, fixed set
of variables. `JAVA_HOME` is not among them, so Maven resolves whatever JDK that
rebuilt PATH offers first — Java 25 in this series, where the launcher had
selected 21. Nothing in the series failed because of it, and Mockito attaches
correctly on both once the agent is loaded explicitly.

It is still a gap in what the evidence can claim: a trial reports the toolchain
it was configured with, not the one that ran. We accept it for now rather than
add `JAVA_HOME` to the passthrough, because the obvious fix has a failure mode
of its own — the sandbox denies reads under `HOME`, so inheriting a JDK
installed there would replace a reporting gap with tests that no longer run.
Closing it properly means either recording the interpreter each phase actually
used, or letting the profile declare its toolchain root and granting that path.
Neither is guesswork we should do without measuring.
