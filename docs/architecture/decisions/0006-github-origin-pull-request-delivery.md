# 6. GitHub is an origin, and a pull request is how work is delivered

Date: 2026-08-30
Status: accepted
Depends on: [ADR 2](0002-container-runner.md)

## Context

Today a run starts from a local directory and ends by writing back to it.
`create_run_copy` copies the source into `workspace/runs/<run_id>`, the agents
work on the copy, and `apply_service` writes the result to the original after a
human confirms, guarding it with content hashes and a restore path.

That shape assumes the operator has already cloned the project and will review a
diff in their working tree. The product this is becoming is pointed at a
repository URL and expected to hand back something reviewable.

## Decision

A repository is an origin. Cloning it into `workspace/runs/<run_id>` *is* the run
copy — the same isolation as today with a different source, so nothing about the
workspace model changes.

Delivery is a branch and a pull request. Where a run audits rather than changes,
the delivery is an issue. The human remains the one who merges.

## Alternatives rejected

**Keep apply-to-worktree and let the operator push.** It works, and it wastes
what git already provides. The hashes and the restore path exist to detect that
the source moved under us and to undo a bad write; a branch cannot corrupt the
default branch and a pull request is reviewable by construction.

**Commit to the default branch directly.** Never. The gate is the review, and
removing it removes the reason a human is in the loop.

**Merge automatically when the evidence gates pass.** The gates are good enough
to reject work, which is not the same as being good enough to accept it
unattended. [Finding 7](../findings/README.md) is the example: the gates caught a
rewrite that had deleted fifteen symbols, and they caught it only because tests
existed and failed to import.

## Consequences

A GitHub port is needed alongside the existing repository port, with the same
minimum-privilege discipline. It reads, clones, pushes branches and opens pull
requests, and it does not need more than that.

**Cloned repositories carry secrets.** Reviewing the six candidate repositories
turned up a database password committed in an `appsettings.json`. That is exactly
what [finding 2](../findings/README.md) excluded manifests for, and it now
arrives over the network from repositories nobody on this side audited. Evidence
exclusion is no longer a nicety.

**Repository contents are data, never instructions.** A README or an issue body
in a cloned project can contain text addressed to an agent. It is input to be
summarized, not direction to be followed — the same boundary the reviewer
diagnostics already carry when they reach the Developer.

Running someone else's build is the threat model the container in ADR 2 was built
for, so this capability depends on it rather than merely benefiting from it.

Rate limits and authentication become operational concerns the local filesystem
never had, including what happens to a half-finished run when a token expires.

## What the first real pull request measured

It deleted fifteen lines. The project already had a `.env.example` documenting a
JWT secret the file itself says has no default and fails at startup without, and
the proposal wrote over it.

Adding to a file and replacing it are different acts, and nothing here should be
able to do the second by accident. A proposal now separates the two: files it
creates, which are refused if the project already tracks them, and files it
extends, which keep what was there. The check is against the base branch and not
the working tree, because a second delivery legitimately rewrites the file the
first one added — what must never be replaced is the project's own.

Two smaller things came from the same run. `--force` was removed entirely: if the
branch already exists on the remote, the delivery builds on it, so an ordinary
push suffices and a tool writing into someone else's repository cannot discard
history at all. And the secret check had to learn the difference between a
credential and a placeholder — `POSTGRES_PASSWORD: ${VAR}` and
`DB_PASSWORD=change-me` are what these artefacts are *for*, and refusing them
would have refused the delivery the check exists to protect.
