# 18. Missing infrastructure is a blocking prerequisite, delivered on its own

Date: 2026-09-10. Status: accepted, partially implemented.
Builds on: [ADR 5](0005-services-per-run.md), [ADR 6](0006-github-origin-pull-request-delivery.md),
[ADR 12](0012-a-started-database-is-not-a-prepared-one.md).

**Correction, 2026-09-11:** this record was accepted as "not implemented". The
delivery half now exists: `infrastructure_prerequisite.py` detects the case,
opens the infrastructure-only pull request first, and stacks the functional one
on it with a body that says what its evidence is worth. Two claims below are
*not* satisfied -- the retry, and what the bring-up actually exercises -- and
both are corrected at the end of this record.

## Context

[ADR 5](0005-services-per-run.md) reads the project's compose file and starts
what it declares. `_split_services` refuses anything carrying `build:` — that is
the project's own code, not infrastructure — and starts the rest. When the
project declares nothing, `ServicesMCP` infers a topology from the connection
strings the configuration already contains and writes a derived compose file to
run against.

Then `down()` deletes it: `self._derived_file.unlink(missing_ok=True)`. The
inference is real work, it is correct often enough to run a suite against, and
its output is discarded every time. The project it was inferred from gains
nothing. The next run infers it again.

Two things on this host show what that costs.

`NorthgateTollPlaza` got the good outcome once. Run `aset-adr6-first` opened
[PR #1](https://github.com/full-stack-dev-johncastrosanabria/NorthgateTollPlaza/pull/1):
two files, 31 lines, `docker-compose.yml` and three lines added to
`.env.example`, no application code touched. The description says where the
values came from — the `application.yaml` of each service — states the engine
versions as an assumption because the project declares none, and says
credentials are read from the environment. That pull request is durable
developer experience: a person who clones the repository afterwards runs
`docker compose up -d` and the tests find what they expect.

`InterviewCleanApi` got the bad one. The project has no compose file. What
exists instead is a `mysql:8.4` container named `icapi-mysql`, started 2026-09-08
by a plain `docker run`, carrying that project's real database name and root
password in its environment and holding a 218 MB anonymous volume. It has no
compose labels, so ADR 5's path did not start it. It has outlived by two days
whatever needed it, and — as
[ADR 16](0016-every-docker-resource-carries-its-run.md) records — its provenance
can no longer be established from anything on the machine. The infrastructure a
run needed became permanent, unlabelled, uncollectable state on a developer's
laptop, holding a credential in plain text.

**Corrección fechada, 2026-09-11.** El contenedor `icapi-mysql` descrito arriba ya no existe en este host; fue retirado a mano y el inventario de esa fecha, en [estado](../../status.md), lo confirma. Lo que motiva esta decisión sigue en pie: el registro de haberlo dejado vivir dos días de más es lo que prueba el problema, y ese registro no depende de que siga corriendo.

The difference between those two outcomes is not capability. It is whether the
infrastructure was treated as work to deliver or as an obstacle to route around.

## Decision

When a functional task cannot proceed because the project does not declare the
infrastructure it needs, that is a blocking prerequisite. The run pauses on it
instead of improvising past it.

What it does then is open a pull request that contains infrastructure and
nothing else: a compose file, an `.env.example` template, and whatever
documentation states how to start it. No application code, no functional change,
no test edits. PR #1 is the shape — two files, 31 lines, and a description
saying which files the values were read from and which values were assumed
because the project states none.

The functional work then proceeds against infrastructure that exists as durable
project state, and arrives as its own clean pull request. Two records, two
reviews, two things a person can accept or reject independently. A reviewer
looking at the functional change is not also being asked to accept a database
choice buried in the same diff.

**The pause is not the end of the run, and this is the part without which the
rest is worthless.** Having authored the compose file, ASET brings that
infrastructure up and retries the functional requirement on top of it, in the
same run. An infrastructure pull request that nobody exercises is unverified
YAML delivered as if it were work; bringing it up is simultaneously the test
that it is correct and the precondition the functional task was missing.

One retry, not a loop. If the functional work fails against infrastructure ASET
itself just authored, that is a finding to report, not something to grind on
until the run budget is gone.

The functional branch is cut from the infrastructure branch and its pull request
opens with the infrastructure pull request as its base. Calling the second
delivery "clean" and leaving it to merge on its own would be a fiction: it
either cannot build without the first, or it silently contains the compose file
again. It is a stacked pull request and it says so.

It also says what its evidence is worth. The suite ran green against
infrastructure that no human has reviewed yet. If a reviewer changes the compose
file before merging it, the functional pull request's recorded evidence
describes an environment that no longer exists, and the body of that pull
request has to state the dependency plainly enough that the reviewer knows to
ask for a re-run.

Reuse needs no mechanism. Because the compose file is committed to the project,
the next run against that project finds a declared topology and takes
[ADR 5](0005-services-per-run.md)'s ordinary path -- there is no ASET-side
store of project infrastructure, and nothing kept running between runs. The
infrastructure is durable because it is in the repository, not because a
container stayed alive; what persists is the declaration, never the process.
That is also what "it is not integrated into the code" means here: a compose
file and an `.env.example` are developer experience, they touch no application
code, and they are reviewed as scaffolding rather than as behaviour.

The rule that makes this different from what happens today: **infrastructure a
run needs and the project does not declare is either delivered or refused.** It
is never conjured for the duration of a run and left behind. If a run starts a
database, that database is labelled, run-scoped and reaped
([ADR 16](0016-every-docker-resource-carries-its-run.md)); if the project should
have one permanently, it arrives as a pull request; there is no third path in
which state simply appears on the host.

ASET reads real credentials while doing this -- the topology inference works
from the configuration files a project ships, and on this host those files
contain live passwords. Nothing it writes may carry them.

Credentials follow what PR #1 already did: values come from the environment,
`.env.example` carries the template, nothing secret is committed. That is also
what [ADR 13](0013-a-prompt-is-redacted-before-it-is-refused.md) requires of
everything else that leaves the system.

Starting the services is not finishing the job.
[ADR 12](0012-a-started-database-is-not-a-prepared-one.md) still holds: a
started database is not a prepared one, and an infrastructure pull request that
brings up an empty engine the suite cannot use has not delivered the
prerequisite it claimed to.

## What this does not decide

**How a project's containers are grouped.** That was decided in
[ADR 16](0016-every-docker-resource-carries-its-run.md) -- one labelled compose
project per project, not one physical container -- and this record does not
depend on it either way.

**How the blockage is detected.** That a missing declaration blocks, and what
happens when it does, is what this record fixes. Which signal identifies it — a
failed connection, an inference that found connection strings pointing at
nothing, an explicit declaration check — is implementation, and the first
version will probably be narrower than the rule.

## Consequences

A functional task can now end without functional code, having produced an
infrastructure pull request and stopped. That is a success, not a failure, and
anything that reports run outcomes has to be able to say so — a router that
reads "no code changed" as a failed run would turn the correct behaviour into a
repair loop.

Two pull requests where there was one means the second waits on the first being
merged, or is stacked on it. Both are worse for latency than improvising, and
that is accepted: the improvised path is what left a MySQL container running for
two days with a password in its environment.

The inference in `ServicesMCP` acquires a second consumer. Today it feeds a
temporary file that is deleted; under this record the same analysis is also the
draft of a file a person will review. That raises its bar. A compose file good
enough to run a suite against for ten minutes is not automatically good enough
to commit to someone's repository, and the pull request has to state its
assumptions — as PR #1 did with the engine versions — rather than present a
guess as a finding.

A second consequence of the retry is that the run gets longer and its Docker
footprint roughly doubles in the worst case, on a laptop that is also the
operator's work machine. The cap of one retry is what bounds that, and the
teardown of [ADR 16](0016-every-docker-resource-carries-its-run.md) applies to
the retry exactly as to the first attempt -- including when it fails.


## Implementation note, 2026-09-11

**The detecting signal is the narrow one this record predicted.** A run is
treated as standing on a blocking prerequisite when `ServiceStack` had to
*derive* the topology rather than read a declared compose file. That is the case
that produced the evidence above, and it is already computed -- `services.derived`
-- so nothing new infers anything. A failed connection would catch more cases;
it is not needed to catch this one, and adding it now would widen the rule
before the narrow version has been exercised against a real project.

**There is no retry, because in this implementation there is no first failure.**
This record describes a run that tries the functional work, is blocked, authors
the infrastructure, brings it up and *retries*. What the code does is derive and
start the infrastructure before the functional work begins, so the functional
work has never failed for want of it, and the "one retry, not a loop" cap has
nothing to cap. The substance the record cared about -- that the infrastructure
is brought up and the functional work proceeds on top of it in the same run --
holds by construction. The wording does not, and the difference matters the day
detection moves to a failed connection, at which point the retry and its cap
have to be written rather than assumed.

**Bringing it up is not quite a test of the file that is delivered, and this
record claimed it was.** `derive_compose` renders two things from the same
analysis: a `run` document, which closes the network and publishes no ports, and
a `delivery` document, which publishes on localhost and turns credentials into
variables. The run starts the first; the pull request contains the second. So
what is exercised is the topology -- the engines, the versions, the healthchecks,
the database names -- and not the rendering a developer will run. A port
collision or an unset variable in the delivered file would not be caught by the
run that proposed it. Narrowing that gap means either bringing up the delivery
rendering as well, at the cost of publishing ports on the operator's machine, or
saying plainly in the pull request that the published form is untested. The body
currently says neither, which is the honest description of where this stands.

**What is implemented, precisely.** Detection from a derived topology; the
infrastructure-only proposal, which adds `docker-compose.yml`, appends to
`.env.example` and touches no application code; the ordering, so the
infrastructure pull request opens before anything functional; the stacked
functional branch, cut from the infrastructure branch and opened against it; and
the paragraph in the stacked body stating that the suite ran green against
infrastructure no human has reviewed, and that changing it invalidates the
evidence. `run_on_project` records `infrastructure_prerequisite`,
`infrastructure_branch` and `infrastructure_pr_url` in its evidence, so a router
can tell an infrastructure-only success from a run that changed nothing -- the
consequence this record said anything reading run outcomes would have to handle.

Stacking required one change to [ADR 6](0006-github-origin-pull-request-delivery.md)'s
delivery, whose invariant was that a proposal never chooses what it is merged
into. That invariant is intact: the base is an argument the caller passes, not a
field on the `Proposal`, and it is refused unless it names a branch under this
system's own `aset/` namespace.

## Corrección fechada, 2026-09-11

**El orden sigue siendo derivar y levantar antes de lo funcional; no hay
reintento porque no hay primer fallo que reintentar.** Eso ya lo decía la nota
de implementación anterior sobre la detección del prerequisito, y sigue
valiendo para la puerta que se añadió después: `deliver()`, en
`infrastructure_prerequisite.py`, invoca `validate_delivered_compose` antes de
abrir el pull request -- no después, y no en un reintento. Cuando la
comprobación se hizo y falló, la entrega se rehúsa con `DeliveryRefused` y ahí
termina; no hay una entrega previa que hubiera fallado y a la que volver.

**La sustancia de la regla se cumple.** La infraestructura se deriva, se
entrega como pull request propio, se levanta de verdad contra un daemon real y
el trabajo funcional se apila encima. Así lo confirma el runner de esta rama,
[`adr18/verify_infrastructure_prerequisite.py`](../../../evaluation/benchmarks/adr18/verify_infrastructure_prerequisite.py):
11 de 11, salida 0.

**Lo que ese resultado no dice: la comprobación es estática.**
`validate_delivered_compose` (en
[`delivery_check.py`](../../../src/engineering_team/delivery_check.py))
resuelve el archivo `delivery` con `docker compose config` contra un `.env`
sintético y compara las variables que interpola con las claves de
`.env.example`. Eso deriva la validez de la *forma* del archivo, no de
haberlo levantado -- y deja fuera lo mismo que este registro ya anticipó al
hablar de la detección del prerequisito: la señal es más estrecha que la
regla, y falla en silencio ante infraestructura que no supo predecir. Un
servicio que pasa `compose config` y aun así no arranca porque el motor
rechaza esa contraseña, o dos servicios que compiten por el mismo puerto en la
máquina de quien lo levanta, no los atrapa nada de esto. Una detección por
conexión fallida -- levantar el `delivery` de verdad y comprobar que algo
responde -- cubriría más de esos casos, y ese día la redacción del reintento
de este registro volverá a importar: intentar la conexión, fallar, reintentar
una vez, dejaría de ser una descripción vacía.
