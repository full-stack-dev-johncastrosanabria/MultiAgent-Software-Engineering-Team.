# 10. Integration tests run under the process sandbox, not the container runner

Date: 2026-09-07. Status: superseded by [ADR 15](0015-container-only.md).
Decision superseded by: [ADR 15](0015-container-only.md); the process
sandbox this record selects no longer exists. Constraint lifted by: [ADR 14](0014-a-docker-api-that-is-not-the-hosts.md), which
supplies the run-scoped Docker API this record said it lacked. The refusal to
mount the host socket is unchanged.

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

## Decided alongside this: the JDK is passed through when it is readable

`ProcessRunner` rebuilds the child's PATH and passes through a small, fixed set
of variables. `JAVA_HOME` was not among them, so Maven resolved whatever that
rebuilt PATH offered first — Java 25 in this series, where the launcher had
selected 21. Nothing failed because of it, and Mockito attaches correctly on
both once the agent is loaded explicitly. But a trial reported the toolchain it
was configured with rather than the one that ran, and that is not a claim
evidence should make loosely.

Adding it unconditionally has a failure mode of its own: the sandbox denies
reads under `HOME`, so a JDK installed by a per-user version manager would be
named to Maven and then refused — trading a reporting gap for tests that cannot
start. It is therefore passed through only when the boundary can read it, which
covers the system locations JDKs usually occupy, and dropped otherwise, leaving
the previous behaviour exactly as it was for the case that would break.

A run now executes the toolchain it names, and where it cannot, it says nothing
rather than something false.
