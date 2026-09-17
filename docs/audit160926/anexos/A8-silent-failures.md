> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A8 — Silent failures (ecc:silent-failure-hunter) — report as returned, with lead adjudication

## Lead adjudication (verified against code at 92742b7)
- F1 docker sweep: VERIFIED `docker_labels.py:92-102` `_listed` returns `set()` on OSError/SubprocessError/non-zero exit; `_removed` `:116-128` drops failures silently; `apply_run.py:211` discards `sweep()` result. Severity adjusted CRITICAL → HIGH (hygiene/resource leak, not wrong agent decision). Correlates with leftovers in flaskapiproduct-dry-20260916a/k.
- F2 model-health ledger: VERIFIED `llm/model_health.py:108-114` and `:127-138` swallow errors without log. MEDIUM.
- F3 broad except in cloud: plausible, not reproduced. MEDIUM, 0.5.
- F4 all-skipped python suite credited as happy_path: PARTIALLY VERIFIED `agents/testing.py:164-170`. pytest exits 5 when no tests are collected (non-zero → not SUCCESS), so the hole is "all collected tests skipped" (exit 0). Severity adjusted HIGH → MEDIUM, confidence 0.5.
- F5 fenced JSON: non-issue.

## Findings (original text condensed)
1. Docker sweep treats query/removal failures as "nothing to clean" — `docker_labels.py:92-102,116-128`, `apply_run.py:211`. The benchmark `run_cycle.py:36-56` already has `DockerQueryFailed`; production code never adopted it. Fix: distinguish query-failed / nothing-found / removal-failed; log the sweep report.
2. ModelHealth corrupt/missing ledger and write failures fully silent — `llm/model_health.py:108-114,127-138`. Fix: warn/trace event while still failing open.
3. Broad `except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError)` at `llm/cloud.py:629` can reclassify internal bugs as provider errors and burn the chain. Fix: isolate network call from parsing; log type+traceback for TypeError.
4. Python profile: `mcp/quality.py` test phase sets fail/unavailable-on-output only for `phase == "security"` (`:638-647`); `agents/testing.py:164-170` credits `happy_path` to any SUCCESS with `test_cases is None`. An all-skipped suite is green evidence. JVM/.NET are report-aware and safe. Fix: parse pytest summary; 0 passed → no coverage.
5. `_json_payload` single fenced block (`llm/cloud.py:164-177`) — defensible.

## Handled well (fail-closed)
- `llm/cloud.py:566-581` relayed provider errors, `finish_reason == "length"` → `_IncompleteOutput`, `_GovernedContradiction`.
- `llm/cloud.py:215-221,688-692` KeyError detail redaction.
- `mcp/quality.py:1388-1465` .NET exit-zero internal errors guarded; `O_NOFOLLOW` report reads.
- `mcp/quality.py:718-722` truncated output → UNAVAILABLE.
- `mcp/quality.py:1590-1599` aggregate keeps dependency-scan provenance (F-8 class).
- `agents/reviewer.py:363-398` status-agnostic coverage gate; evidence citing tools that never ran is rejected.
- `apply_run.py:236-240` cleanup on BaseException with re-raise.
- `delivery.py` / `apply_run.py:556-759` `DeliveryRefused` fail-closed and recorded.
