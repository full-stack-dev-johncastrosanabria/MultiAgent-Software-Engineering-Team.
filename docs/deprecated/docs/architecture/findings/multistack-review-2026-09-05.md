# Independent multistack review — 2026-09-05

Reviewed ASET base `4bb7e8e` through `a83ccdc`, including the pending secondary-key
redaction correction. SPEC: **NO PASS**. QUALITY: **NO PASS**.

The previous single-network finding is resolved: service discovery collects every
network and ContainerRunner connects each additional network before starting the
command. No new finding in compatible environment merges for shared build contexts.

## Findings at review time

1. **P1 — Host mounts escape the checkout.** `services.py:330-341` accepts writable
   bind sources outside `ServiceStack.root`, including sources reached through a
   symlink. Named volumes with `driver_opts: {type: none, o: bind, device: ...}`
   bypass the socket check too. The newly active apply lifecycle automatically runs
   image-only Compose services with those mounts, permitting host writes outside the
   selected checkout. Local model validation accepted both an outside bind and a
   volume-driver bind; no container was started.
2. **P1 — Textual secondary credentials are not redacted.**
   `guardrails/secrets.py:119-137,217-220` does not recognize the `_2` suffix even
   though structured dictionaries do. A fixture assignment remained unchanged,
   passed the outbound guard, and appeared in trace and run-event status text.
   The parent agent's pending regex correction addresses this finding; its final
   verification remains part of the next gate.
3. **P2 — Canonical-marker masking accepts remaining credential text.**
   `guardrails/secrets.py:131-133` treats whitespace after `[REDACTED]` as a complete
   value boundary. Redacting a valid unquoted properties/YAML password containing
   spaces leaves its remaining words, then the new exemption allows that residue
   into cloud context. Direct and JSON-encoded fixtures reproduce the acceptance.
4. **P2 — Interrupting infrastructure startup skips teardown.**
   `apply_run.py:213-215` catches only `Exception` while entering the context.
   `KeyboardInterrupt` from `ServiceStack.up` bypasses both this handler and the
   context's not-yet-active exit handler. A fixture recorded `init, up` without
   `down`; real services already created by Compose can remain running.
5. **P2 — Pacing is scoped to the report directory.**
   `evaluation/benchmarks/multistack/run_trial.py:48-49` places both lock and journal
   under `report.parent`. Two mocked trials with reports in distinct directories
   were accepted with zero seconds between completion and start. A common canonical
   state location is required for the documented cross-repository interval.

## Limits and next gate

This review used static inspection and deterministic fixture reproductions. It made
no provider calls, started no infrastructure, and did not rerun broad suites.
External target repositories are outside this review's scope.

## Correction evidence

Findings 1–4 now have corrections and passing deterministic regressions:

- Bind sources resolve against the checkout, including symlinks, and are rejected
  when they escape it. Named-volume driver options are refused because renaming a
  bind-backed volume does not isolate its device. Checkout-local initialization
  scripts remain supported. Eight regression cases cover these boundaries.
- Numbered API-key assignments receive the same redaction, outbound validation and
  delivery rejection as primary credentials. Direct and JSON-encoded fixtures cover
  unquoted, single-quoted and double-quoted secondary assignments.
- Plain properties/YAML secret values are redacted to their line end, since spaces
  and punctuation can be part of the credential. Bare canonical markers are exempt
  only at a line boundary. Regressions verify full removal, rejection of residue and
  preservation of the next non-secret line.
- Failed context entry cleans up on BaseException. KeyboardInterrupt and SystemExit
  retain their identity after teardown; repeated closure does not clean up twice.

Finding 5 was corrected separately in `f83137d`: lock and journal share the canonical
experiment workspace, with six passing benchmark regressions.

Correction validation: 114 focused tests passed with exit code 0 across guardrails,
delivery, apply infrastructure, service topology and apply delivery. Ruff passed for
the six changed source/test files, and `git diff --check` passed. No model provider
was called and no infrastructure stack was started for these regressions.

Independent correction review by the root agent (separate from the correction
implementer): **PASS** for these five findings. The root inspected the final source
and regression diff, including symlink traversal, preservation of cancellation
identity, complete removal of plain scalar credentials, secondary-key delivery
rejection, and shared pacing state. The 114-test terminal success, Ruff and diff
checks are the validation evidence. This closes the ASET correction gate only;
three approved model runs, destination verification and PR delivery remain pending.
