# 12. A started database is not a prepared one

Date: 2026-09-08. Status: accepted.

## Context

ADR 5 gave a run the services a project declares: `ServiceStack` reads the
configuration, starts what it names, and publishes the connection string the
commands should use. For `InterviewCleanApi` it does this correctly and without
help — from `appsettings.json` alone it derives a MySQL dependency and produces
`ConnectionStrings__DefaultConnection=server=mysql;port=3306;database=InterviewCleanApiDb;…`.

The suite still failed. Ten of its sixteen tests could not find their tables.

Nothing was wrong with the service. A database that has started is empty, and
this project's schema lives in EF Core migrations that only an explicit command
applies. The tests never applied them: they passed on developer machines
because someone had run `dotnet ef database update` by hand at some point, and
against anything freshly started — a service container, a clean CI job — they
reported a broken suite when what they had met was an unprepared schema.

That misreading is the one finding 7 named, and it is expensive in a way that
compounds: a red gate for an infrastructure reason routes the Developer back
into code that is fine.

The obvious alternative was to fix the repository, and it was tried: a module
initializer applying the migrations when the test assembly loads took the suite
from 6/16 to 16/16 against an empty database. It works, and it is a defensible
change for that repository to make on its own account. It is not an answer for
the harness, because it requires every project the team ever runs against to
have already made it.

## Decision

Between the services becoming ready and the first phase running, the run brings
the database up to the schema the project declares.

A profile says how its toolchain applies migrations (`schema_template`) and, if
its image does not carry the tool, how to obtain one (`schema_tool_template`).
Only `dotnet` declares these today. A stack that declares neither applies no
schema, which is an answer rather than a gap.

The two projects a migration command needs — the one that owns the migrations
and the one whose configuration names the connection — are found by path: a
directory holding `Migrations/*.Designer.cs`, and one holding `Program.cs`.
More than one candidate of either kind applies nothing. Migrating a project
nobody named is worse than migrating none.

The step runs after the services because the command needs the connection
string they publish, and before every phase because every phase after it
assumes the schema is there. A migration that will not apply is reported as
`INFRASTRUCTURE_ERROR` and stops the run, not as a failing test.

## Consequences

A project whose schema comes from migrations now runs against a service the
harness started, with no manual preparation and no change to the project. The
repository-side fix that proved the diagnosis becomes unnecessary, which is the
outcome worth having: the change the run publishes is the change the run made.

The cost is a tool install into the run's own environment on the first phase
that needs it — kept out of the image and off the host, and reused across the
run's phases, which is why the command is `tool update` rather than
`tool install`: installing twice is an error where updating is not.

This does not seed data. It creates the schema a project declares and stops
there; a fixture that needs rows still writes them.
