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
  prompt. It is now replaced by `[REDACTED]`. The value itself does not reach
  the model in either case.
- **The rest of that prompt now travels, and that is a widening.** Refusing on
  one detected secret withheld everything around it as collateral, including
  credentials the detector does not recognise. `InterviewCleanApi`'s README is
  the case in point: it was refused over `**Password:** …`, and it also says
  `Admin user: john@test.com / 123456` in prose, which no pattern matches.
  Redacting the first line lets the second one through.

That protection was real but arbitrary — it applied only to files that happened
to also contain a *detected* secret, and never to the ones that did not. Trading
it for the ability to reason about a project at all is the judgement this record
makes, and it is a trade, not a free win.

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

Detection is now the only thing standing between a credential and a cloud
prompt, where before a neighbouring match could shield it by accident. That
raises the value of the patterns themselves, and two gaps are already on the
record from this repository alone: a credential written as prose
(`user: x / 123456`) and one written as a form default (`useState('123456')`).
Improving that detection is separate work, and it is now worth more than it was.

Three defects in the redactor surfaced while proving this, all of them older
than this decision and all fixed here: it mangled TypeScript type annotations
(`password: string` became `password=[REDACTED]`, corrupting the source the
model reads); it did not recognise its own marker mid-line, so redacted text
failed the very check that follows it; and against documentation it redacted the
markdown emphasis instead of the value, leaving `**Password=[REDACTED] `123456``
with the credential in plain sight.

Related: ADR 5 is the reason the password is in the file at all.
