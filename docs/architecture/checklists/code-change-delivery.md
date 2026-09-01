# Code-change delivery

A code pull request counts as delivered only when every item below is true. The
first evidence for this checklist is
[FlaskApiProduct PR #1](https://github.com/full-stack-dev-johncastrosanabria/FlaskApiProduct/pull/1),
which also showed why operator-completed and autonomous deliveries must not be
reported as the same result.

## Source and branch

- [ ] Work starts from a fresh clone or an explicitly recorded revision.
- [ ] The delivery branch is new, uses the `aset/` prefix and is never the
  repository's default branch.
- [ ] Commit, push and pull-request creation have explicit human confirmation.
- [ ] Delivery never force-pushes and never merges automatically.

## Scope and evidence

- [ ] Every changed source file was inspected or deterministically selected
  within the authorized task boundary.
- [ ] The complete diff is reviewed before commit; unrelated changes are absent.
- [ ] The selected component runner executes the repository's real tests.
- [ ] Previously passing tests still pass, and new behaviour has specific tests.
- [ ] Build, lint, dependency and security gates report their real status.
- [ ] Coverage is reported when measurable; a threshold is not invented when the
  project has none. ASET's current Python delivery target is at least 80 percent
  on the changed boundary.

## Truthful delivery

- [ ] The pull-request body identifies the requirement, changed files, executed
  commands, results and any residual risk.
- [ ] Missing GitHub status checks are shown as missing, never as green.
- [ ] If ASET stopped at `HUMAN_REVIEW_REQUIRED`, any later operator repair is
  labelled as such and does not count as autonomous product-flow proof.
- [ ] An autonomous delivery claim requires the same ASET run to reach
  `APPROVED` before its delivery backend creates the branch and pull request.
