# Code-change delivery

A code pull request counts as delivered only when every item below is true.

- Operator-completed reference:
  [FlaskApiProduct PR #1](https://github.com/full-stack-dev-johncastrosanabria/FlaskApiProduct/pull/1)
  (John; showed why operator repair must not be reported as autonomous delivery).
- First autonomous ASET delivery:
  [FlaskApiProduct PR #2](https://github.com/full-stack-dev-johncastrosanabria/FlaskApiProduct/pull/2)
  (`apply-debugger-flask-writes-v7`, Reviewer APPROVED, `build_delivery` with
  `DELIVERY_BACKEND=gh` + `--confirm-delivery`).

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


## Run flags (do not guess)

Autonomous delivery from `run-project` / `apply_run` only happens when **all** of
these are true. Missing any one leaves delivery off (safe default).

- [ ] `DELIVERY_BACKEND=gh` in the environment (Settings `delivery_backend`;
  default is `none` — `build_delivery` then returns `None` and no PR is opened).
- [ ] `--authorize-writes` on the CLI (Developer may write via Repository MCP).
- [ ] `--confirm-delivery` on the CLI (`confirm_delivery=True` into
  `run_on_project`; default `--no-confirm-delivery`).
- [ ] Reviewer status is `APPROVED` on that same run (HITL / REJECTED never
  delivers).
- [ ] Written paths have file contents available for `Proposal.updates` /
  `files` (empty proposal → `DeliveryRefused`, recorded as `delivery_error`).

Example (Flask-style autonomous PR):

```bash
DELIVERY_BACKEND=gh .venv/bin/engineering-team run-project /path/to/FlaskApiProduct \
  --spec "…" \
  --authorize-writes \
  --confirm-delivery \
  --report-path evaluation/reports/apply-run.json
```

Evidence fields after a delivery attempt: `delivery_branch`, `delivery_pr_url`,
or `delivery_error`. With `delivery_backend=none` or without `--confirm-delivery`,
those fields stay absent and GitHub Helper (or a later run) must open `aset/…`
manually only after a real APPROVED.

## Truthful delivery

- [ ] The pull-request body identifies the requirement, changed files, executed
  commands, results and any residual risk.
- [ ] Missing GitHub status checks are shown as missing, never as green.
- [ ] If ASET stopped at `HUMAN_REVIEW_REQUIRED`, any later operator repair is
  labelled as such and does not count as autonomous product-flow proof.
- [ ] An autonomous delivery claim requires the same ASET run to reach
  `APPROVED` before its delivery backend creates the branch and pull request.
