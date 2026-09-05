# Live multistack experiments

These results distinguish actual model runs from manual infrastructure preparation.
Run `run_trial.py` with a unique report path; its shared journal and process lock
enforce 180 seconds from completion of the previous experiment, across repositories
in the same workspace. The journal and lock live in `<workspace>/evidence`, so
choosing another report directory cannot bypass the interval or an active run.
The same interval includes the saved Gemini credential probes.

## Ingresos

- Attempt 1, 2026-09-05 03:54 UTC: failed in Architecture before a change was
  authored. The secret guard rejected complete redaction markers in YAML evidence.
  ASET commit `9269d8b` corrects the false rejection while preserving secret checks.
- Attempt 2, 04:04 UTC, run `apply-7b52d857-1812-4091-ac7a-79995846b27b`:
  real cloud models wrote `Order.java` and `OrderTest.java`. The focused tests
  passed on each iteration. The deterministic Reviewer required human review
  because the actual OWASP scan reported vulnerable existing dependencies.
  This is not an approved run. Dependency migration and full integration validation
  are prerequisites for retrying; no scan threshold or test was disabled.
- Prerequisite commit `6c8b722`: Spring Boot 4.1.1 migration passed all 83 tests
  (75 order, 8 payment), including nine real integration tests with no skips.
  Both OWASP scans passed the existing CVSS 7 gate. The Kafka timestamp wire
  format is preserved by explicit configuration and regression tests. The
  model-authored `Order.java` and `OrderTest.java` remain outside that commit.

## Northgate

Manual Docker prerequisite commit `1a10629` on the clone based on
`aset/compose-mongo-postgres` supplies both Java services and Angular, persistent
databases, loopback ports, readiness checks and dedicated test databases.
Observed: 61 backend tests and 26 Angular tests passed inside Docker; frontend
proxy login, tariffs, dashboard, toll pass creation and asynchronous MongoDB audit
delivery passed. A separate security patch update is being validated before ASET.
These are infrastructure results; the requested model-authored change is pending.

## Interview

Baseline .NET output reported 20 passing cases, but four Selenium cases returned
early when their frontends were missing. That output does not prove browser success.
The test infrastructure is being corrected to require live UI assertions before the
low-stock API experiment. Real MySQL was used by the other baseline cases.
