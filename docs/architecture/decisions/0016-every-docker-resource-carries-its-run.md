# 16. Every Docker resource carries its run and its project, and nothing running outlives the run

Date: 2026-09-10. Status: accepted, not implemented.
Extends: [ADR 5](0005-services-per-run.md), [ADR 14](0014-a-docker-api-that-is-not-the-hosts.md),
[ADR 15](0015-container-only.md).

**Nothing in this record is implemented yet.** It states what the system must do
and the evidence that it does not do it today. The code that satisfies it is a
later change; until then, [status](../../status.md) is the honest account of
what actually happens on a host.

## Context

Three records handed Docker a growing share of the system. ADR 5 gave each run
its own compose project, ADR 14 gave it its own daemon, ADR 15 made the
container the only place a target-project command may run. Each of those
lifecycles is closed in-process, by a context manager: `ContainerRunner.close`
removes its named volume, `ServicesMCP.down` runs `compose down -v
--remove-orphans`, `RunDaemon.down` stops the daemon container. When a run
completes normally, the accounting is correct.

The accounting is only correct then. A run that is killed, interrupted, or that
dies with the machine leaves everything it created behind, and nothing in the
repository can find those leftovers afterwards: `grep -rn -- '--label' src`
returns nothing. Not one resource ASET creates carries a marker saying which run
created it, so a reaper cannot be written today without guessing at name
prefixes.

What that produced on the developer's machine, measured on 2026-09-10 before any
cleanup:

| Resource | Found | Note |
|---|---|---|
| Named volumes `aset-env-*` | 10 | one per run that never called `close` |
| Compose volume `aset-<run_id>-postgres_data` | 1 | survived its run's `down` |
| Anonymous volumes | 22 | most attributable to no live container |
| Daemon container `aset-dind-run-f0e96bbe25cb` | 1 | ADR 14 daemon, still present |
| Images `aset-northgate-*` | 5, 1.6 GB | built under a compose project name |
| Images `aset/quality-*` | 3 | no producer found in the current code |
| Build cache | 10.09 GB | 8.4 GB reclaimable; no run ever prunes it |

Volumes alone held 5.12 GB across 36 entries. Total reclaimable was about
19 GB on a laptop the operator also uses for work.

Cleanup reclaimed about 14.3 GB and left 26 images holding 8.33 GB, which was
first read as the operator's own work and is not. The operator states they
pulled none of them, and the dates agree: `northgatetollplaza-*` on 2026-09-05,
`interview-api`, `interview-react`, `interview-vue` and their `-recovery-`
twins minutes apart the same day, `interview-tests` at 2.17 GB that evening,
`frontend`, `payment-ms` and `order-ms` on 2026-09-06, and
`mcr.microsoft.com/dotnet/sdk:10.0` at 944 MB on 2026-09-07 -- the multistack
validation window of [ADR 9](0009-real-multistack-validation.md), stack by
stack. The base images sit in the same window: `mysql`, `postgres`, `mongo`,
`kafka`, `eclipse-temurin`, `python:3.13-slim`, `nginx`, `docker:dind-rootless`,
`docker:cli`, `testcontainers/ryuk`. Of 8.33 GB, roughly 7.5 GB was put there by
ASET; the remainder is the operator's own MCP tooling.

So the leak is not the tail of the problem, it is most of it. Volumes and
containers were the visible part; images are the larger part, and they had been
misread as belonging to the developer precisely because nothing on them says who
made them.

Two findings from that cleanup are worth recording because they are not obvious
and they change what a fix must do:

**`docker volume prune` does not touch named volumes.** Without `-a` it removes
anonymous volumes only. Every `aset-env-*` volume is named, so an operator
running the routine prune reclaims nothing ASET leaked and is left believing
they did.

**`compose down` does not remove images compose built.** Removing containers,
networks and volumes is what `down -v --remove-orphans` does; images built from
a `build:` stanza survive unless `--rmi` is passed. The 1.6 GB of
`aset-northgate-*` is the residue of that gap.

One reason the leak lands on the operator's machine at all is worth stating,
because it was challenged and checked. [ADR 14](0014-a-docker-api-that-is-not-the-hosts.md)
gives a run its own daemon, and everything created inside a daemon dies with it
-- which would make labelling unnecessary. But the run daemon is opt-in and off
by default: `quality_run_daemon_image` is `""` in `config.py`, and a run without
it uses the host's daemon. The default path is the leaking path, so the labels
are not redundant with ADR 14; they are what covers the case ADR 14 does not.

One resource resisted attribution entirely. A `mysql:8.4` container named
`icapi-mysql`, created 2026-09-08, holds a 218 MB anonymous volume and carries
in its environment the database name and root password of a real project on this
host. It has no compose labels, so it was not started by ADR 5's path; it was
started by a plain `docker run --name`. The operator believes ASET created it
during an interview-project trial, and the credentials it carries make that
plausible. It cannot be confirmed. **That is the finding, not a footnote**: with
no labels, the difference between "ASET leaked this" and "a person started this
by hand" is unrecoverable, and a reaper that guessed would eventually delete
something a person needed.

## Decision

Every Docker resource ASET creates carries, at creation, the labels
`aset.owner=aset` and `aset.run=<run_id>`. Containers, named volumes, networks,
compose projects, the run daemon and any image built during a run: all of them,
without exception.

A third label answers a different question. `aset.project=<slug>` says which
project a resource belongs to, and unlike the run id it is stable across runs.
It exists because the run id does not identify anything a person recognises:
`run_id` defaults to `apply-<uuid4>` (`apply_run.py`), and the compose project
name is `"aset-" + run_id`, so a project like `ingresos` -- two microservices,
Kafka and Postgres -- appears as a group called `aset-apply-3f2a...`, different
on every run, saying nothing about the project it serves. That, not the number
of containers, is what makes a host look disorganised.

So the compose project of a run is named after the project, `aset-ingresos`, not
after the run. Docker Desktop groups by compose project, so the four services
collapse into one row carrying the project's name, and one filter --
`docker ps --filter label=aset.project=ingresos` -- lists everything ASET holds
for it. The run id stays on every resource as a label, which is what the reaper
reads.

**The alternative was rejected on purpose.** Grouping the four services into a
single physical container was considered and refused. It would mean writing a
supervisor, one PID 1, one log stream, no per-service health check or restart,
and -- the reason that decides it -- a runtime that does not match how the
project actually deploys, so a green suite would stop being evidence about the
real system. [ADR 5](0005-services-per-run.md) takes the topology from the
project's own compose file, and rewriting it into a monolith would make ASET
test something the project does not have. Grouping is a name and a query, not a
packaging decision.

Resources also carry `aset.lifetime`. `run` is everything that runs or holds
state -- containers, networks, service volumes, the environment volume -- and it
is reaped without exception. `cache` is content that a later run can reuse
without inheriting anything: pulled base images, build cache, package caches.
Nothing stateful is ever `cache`, and nothing running is ever anything but
`run`. That line is what keeps a reused Postgres from carrying last week's rows
into this week's evidence, which [ADR 12](0012-a-started-database-is-not-a-prepared-one.md)
already warns about from the other direction.

A run reaps what it labelled, and the ordinary in-process teardown stays as it
is. What the labels add is the ability to reap after a crash: a startup sweep
removes anything labelled `aset.owner=aset` whose run is not the current one,
and an explicit operator command does the same on demand. Build cache produced
by ASET runs is included in what the sweep reclaims.

An image a run builds is garbage the moment the run ends, and is labelled and
reaped like everything else. An image a run pulls is not: re-pulling
`postgres:17-alpine` for every run would trade disk for bandwidth and startup
time, and that is a bad trade. Pulled base images stay, as a cache this record
makes explicit -- declared in one place, listed by one command, dropped by one
command. What is refused is the present situation, where the cache is not a
decision but an accumulation nobody chose and nobody can enumerate.

The label is what makes deletion safe. Nothing without `aset.owner=aset` is ever
touched, so a container like `icapi-mysql` — whose provenance cannot be
established — survives every sweep by construction. The reaper is deliberately
biased toward leaving unlabelled state alone, because the cost of deleting a
person's database is not comparable to the cost of leaving a stale volume.

## What this does not decide

**Whether infrastructure may be kept running between runs.** It may not, and
the reasoning is in the `aset.lifetime` split above. What is reused across runs
is the project's committed compose file
([ADR 18](0018-missing-infrastructure-is-a-blocking-prerequisite.md)) and
content-addressed caches — never a live container, never a stateful volume.

**Where the project's files live.** That is [ADR 17](0017-the-project-lives-in-the-run.md).

## Consequences

An operator can answer "what is ASET holding right now" with one `docker ps
--filter label=aset.owner=aset`, which is not possible today.

A crashed run stops being permanent. The cost is that a sweep runs at startup
and can, in principle, delete resources belonging to a concurrent run on the
same host; the `aset.run` label is what keeps that from happening, and any
implementation that reaps by owner alone would be wrong.

Labels are metadata, not a boundary. Nothing here changes what a container can
reach; ADR 14 still owns that. A process with access to the daemon can remove
labelled resources or forge the label, and this record does not pretend
otherwise. It is bookkeeping, and its value is exactly that of honest
bookkeeping: it makes the leak visible and the cleanup safe.

Naming the compose project after the project instead of the run has one real
cost: two runs against the same project at the same time would collide on that
name. This record accepts that and makes it explicit -- a second concurrent run
on a project already held by another is refused, by name, rather than allowed to
share a compose project with it. A solo operator loses nothing; a setup that
genuinely needs concurrent runs on one project would have to trade the grouping
back for per-run names, and should do that as a decision rather than by
appending a suffix until the collision stops.
