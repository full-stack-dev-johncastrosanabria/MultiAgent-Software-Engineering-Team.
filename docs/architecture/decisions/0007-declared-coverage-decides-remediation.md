# 7. A stage declares what it could not see, and the router believes the count

Date: 2026-08-31
Status: accepted
Refines: [ADR 4](0004-profile-per-component.md)

## Context

Architecture reads a bounded slice of a repository. Until now it had no way to
say the slice was thin, and no consumer that would have listened. Two things
followed from that, and both were observed rather than predicted.

A design built on four files of four hundred was presented exactly like one built
on the whole repository. That is finding 1's failure — not distinguishing "found
nothing" from "did not look" — moved from the output to the input.

And every test failure was routed to the Developer. That is right when the design
was sound and the code was not. It is wrong when the design was a guess: the
Developer is asked to satisfy interfaces nobody verified, produces the same
mismatch, and the cycle repeats. Worse, `relevance_terms` was a pure function of
the specification and the requirement, neither of which a remediation changes, so
the second pass read the same files and reached the same conclusion. The loop had
no exit.

## Decision

**Coverage is measured, not confessed.** The graph compares what it read against
what ranking said was worth reading, and stamps the result onto the proposal. The
model's opinion of its own thoroughness is not consulted. A stage that overlooked
something is the last thing that can be trusted to report it, and a routing
decision must not rest on free text — the invariant the whole design stands on.

**Silence is a third state.** `evidence_sufficient` is `True`, `False` or `None`.
`None` means nothing was recorded, which is not a clean bill of health. Older runs
and unmeasured paths land there and are treated as unknown rather than fine.

**A failure over declared-thin evidence belongs to Architecture.** The Reviewer
sends it back to the stage that could not see, not to the stage that could not
guess. Thin evidence on its own rejects nothing: incomplete reading is a reason to
distrust a failure, not to invent one.

**Remediation changes what gets read.** The Reviewer's feedback contributes terms
to file selection. The names in a failure — the module that would not import, the
attribute that did not exist — are exactly the terms that would have found the
missing file.

**A focused task has focused boundaries.** For an explicit HTTP endpoint, the
graph derives the resource and reserves the named test plus conventional
route/controller and model/domain files. A broad word such as `stock` must not
push the endpoint's owning boundary out of the bounded evidence window.

**A remediation spends its next window on unseen evidence.** The audit retains
all historical reads, but Architecture receives the current visible window. Task
boundaries remain visible on every pass; the remaining slots rotate to paths not
read in an earlier Architecture pass.

## Alternatives rejected

**Ask the model whether it saw enough.** It is the cheapest signal and the least
trustworthy: the same reasoning that missed a file is the reasoning that would
report on the miss, and it would put a routing decision downstream of free text.

**Default `evidence_sufficient` to `True`.** Every run before this change would
then assert coverage it never had, which is the exact conflation this ADR exists
to remove.

**Route on the failure's text instead.** Reading "ImportError" and inferring an
interface problem is a heuristic over model-adjacent output. The coverage count is
a fact the graph owns.

## Consequences

Remediation can now go somewhere other than the Developer, so a run can spend
cycles re-reading rather than re-writing. That is the intended trade: reading
again is cheap next to implementing against interfaces that do not exist.

The threshold — half the ranked candidates — is a fallback judgement, stated in
one place and easy to move. When a task has at least two deterministic boundaries,
every one must be visible; otherwise the proposal declares exactly which boundary
was missed. Reading everything a small repository has is always sufficient,
however little that is: a three-file project is not a thin slice of itself.

Feedback in the terms and unseen-path rotation make selection depend on review
history, so two runs of the same requirement can read different files. That is the
point, and it means selection is no longer reproducible from the specification
alone.
