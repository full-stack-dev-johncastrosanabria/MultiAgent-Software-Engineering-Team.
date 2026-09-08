# 13. A prompt is redacted before it is refused

Date: 2026-09-08. Status: accepted.

## Context

Two requirements of this system contradicted each other for any project with a
database.

ADR 5 derives a project's services from its committed configuration:
`ServiceStack` reads the connection string out of `appsettings.json` to learn
which engine to start, on which port, with which database and credentials. The
password has to be in that file for the run to work at all.

The cloud guardrail refused any prompt whose content matched
`password\s*[=:]\s*…`. So `InterviewCleanApi`'s Architecture step died on
`sensitive content is not allowed in cloud context`, reading its own
`appsettings.json` — a file that was doing exactly what the harness required of
it. The effect was categorical rather than incidental: no project that declares
a database could use a cloud model.

The module already knew how to redact. `redact_secrets` existed and turned that
same file into `password=[REDACTED]` with the value gone. It was simply never
reached on this path.

## Decision

Content bound for a cloud model is redacted first, and the original refusal then
runs on what redaction left.

The order is the whole safety argument, and it is worth stating precisely
because "redact instead of refuse" sounds like a relaxation and this is not one:

- A value the detector matches was previously withheld along with the entire
  prompt. It is now replaced by `[REDACTED]` and the rest travels. The value
  itself does not reach the model in either case.
- A value the detector does not match was travelling before this decision and
  travels now, unchanged. Redaction does not widen that gap, and does not
  narrow it either.

So nothing that used to be withheld is now sent. What used to abort a run now
arrives with a hole in it.

Two refusals stay refusals, because redacting them would leave nothing worth
sending. A mapping keyed by a secret (`{"password": …}`) and a structure
presenting a credential file's contents (`{"file": ".env", "content": …}`) are
not documents that happen to quote a password; carrying the value is their
purpose.

## Consequences

A project may keep the connection string the harness needs and still use cloud
inference. The agent sees the shape of the configuration — that there is a MySQL
server, on a port, with a database name — which is what it needs to reason about
the project, and not the password, which it never needed.

This changes what happens to secrets that are detected, not how many are
detected. A credential the patterns do not recognise is exactly as exposed as it
was before, and improving that detection is a separate piece of work.

Related: ADR 5 is the reason the password is in the file at all.
