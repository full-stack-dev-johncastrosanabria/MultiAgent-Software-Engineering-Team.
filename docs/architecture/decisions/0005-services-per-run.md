# 5. A project's services live for the run, on a network that reaches nothing else

Date: 2026-08-30
Status: accepted
Depends on: [ADR 2](0002-container-runner.md), [ADR 4](0004-profile-per-component.md)

## Context

Databases never came up because the demo projects use `sqlite3`, which is a
library. It is imported, not started. Nothing had to be running, reachable or
ordered.

Five of the six repositories reviewed are the opposite. They expect a service
already running on a developer's machine: NorthgateTollPlaza's `test.sh` refuses
to start unless `pg_isready` and MongoDB on port 27017 both answer, and tells the
reader to run `brew services start postgresql@18`. Banking points at
`localhost:5432`. BusinessAI-Analytics and InterviewCleanApi point at MySQL on
3306. An autonomous agent has none of that.

It is also not only databases. PruebaNuevosIngresosBackend ships Postgres **and
Kafka**, with an init container and startup ordering.

The container runner from ADR 2 has two network modes and neither works here.
`none` cannot reach a database. `bridge` reaches the database, the internet, and
whatever else is listening on the host.

## Decision

Services are declared per run and live for the run, not for a command. They share
an **internal** network with the component containers: siblings resolve each
other by name, and nothing has a route out. This was verified rather than assumed
— on a `--internal` network a container resolves `db` and cannot open a socket to
1.1.1.1.

Where a repository ships a compose file, **that is the topology**. It already
carries images, healthchecks and ordering, authored by people who know the
project. Where it does not, the topology is derived into an overlay held on the
ASET side.

Readiness is a health check, never a delay. A service that fails to become ready
is recorded as its own evidence.

## Alternatives rejected

**`--network bridge` for anything needing a database.** The simplest change and
the wrong boundary: it hands a project under test the internet and the host's
other listeners in order to give it one port.

**Services inside the per-command container.** Keeps one lifecycle, but a
database that dies with each command loses its state between the migration and
the test that needs it.

**Require a compose file in the target repository.** Same objection as ADR 4:
the repositories are not ours.

**Fixed sleeps for startup.** Postgres is ready in about a second; SQL Server
documents 2 GB of RAM and takes far longer. Any constant is either a flake or a
tax on every run.

**Substitute an in-memory database.** It would remove the problem and the point:
the value is running the project as it actually is, and a project whose tests
only pass against a substitute has not been verified.

## Consequences

The runner gains a third network mode and a lifecycle longer than one command,
which is the first state the container runner has to hold across commands.

**A service failure must not be reported as a test failure.** If the database
never starts, the tests fail, and a gate reading "tests failed" turns an
infrastructure problem into a code problem — the misleading headline that made
[finding 7](../findings/README.md) point at the wrong thing.

The derived topology is itself a deliverable. A compose file that makes
NorthgateTollPlaza run without `brew services` is a useful pull request that
changes no application code.

SQL Server publishes `linux/amd64` only. On Apple Silicon that is emulation, for
a service that starts on every run. Postgres and MySQL publish arm64 and do not
have this problem, so parity between the two engines should not be promised.

## What implementing it measured

Compose is given the project's file and an ASET override as a second `-f`. Three
things about that override were established by running it, not by reading docs.

An empty `ports` list merges with the project's and leaves the published port in
place; only the `!override` tag replaces it. That tag is YAML-only, so the
override is emitted as YAML — which needs no library, unlike the parsing that
finding 2 removed pyyaml for. Parsing is delegated to `docker compose config`,
the same parser that later runs the file.

Closing the `default` network closes nothing when a project names its own.
PruebaNuevosIngresosBackend declares `pedidos-net` and never touches `default`,
so an override that marked only `default` internal produced an isolated network
no container was attached to while the services kept their route out. Every
declared network is closed now, and the network the run actually uses is read
back from a running container rather than derived from the project name.

A compose file may also pin a global network name, as that one does. Two runs
would then share a network and either one's teardown would remove it under the
other, so the override renames each network into the run's own scope.

A container can be given only one network at start, and a command may need both
the project's internal service network and a route to the registry. The runner
therefore creates the container, attaches the second network when the command
declares it needs one, and starts it — `docker run` cannot express this.

## Deriving a topology, and what that measured

Where a project declares nothing, its connection strings are read and a topology
is derived. Reading is extraction rather than parsing: a regex finds
`jdbc:postgresql://host:port/name` in YAML, properties files and JSON alike, and
keeps pyyaml out of the dependency list.

Three things only a real repository showed.

A configuration file may quote a connection string inside a comment.
NorthgateTollPlaza explains a framework quirk by naming the default
`mongodb://localhost/test`, and an extractor that reads prose invents a service
the project does not use. Whole-line comments are dropped before scanning.

One service per engine, not one per database: two databases behind the same
Postgres are one container.

A derived file needs healthchecks, and forgetting them fails silently. Compose's
`--wait` waits for running rather than ready without one, so a derived Postgres
reported up in a second and refused the connection that followed. This ADR
already said readiness is a health check and never a delay; the derived rendering
had to be made to honour that too. The probes are also asserted to contain no
character that would break the document they are written into, after a Mongo
probe with double quotes produced a file compose refused to parse.
