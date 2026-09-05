# Northgate: deterministic pass normalization

Repository: https://github.com/full-stack-dev-johncastrosanabria/NorthgateTollPlaza
Bootstrap input: aset/compose-mongo-postgres. Component: northgate-backend (Java 21).

Fix PassService so license-plate normalization is independent of the server's default
locale. Preserve whitespace trimming, fare snapshot, lane/shift ownership, persistence,
audit payload, existing payment parsing, and public DTOs. Reject a null or blank plate
with IllegalArgumentException before saving a pass or publishing an audit event.

Use Locale.ROOT for case normalization. Do not change authentication, database schema,
tariffs, or unrelated endpoints. Keep existing tests and add regression tests using
the existing Mockito and AssertJ patterns in PassServiceTest.

Source: northgate-backend/toll-service/src/main/java/com/john/northgate/toll/service/PassService.java
Tests: northgate-backend/toll-service/src/test/java/com/john/northgate/toll/service/PassServiceTest.java

## Acceptance tests

1. With JVM default locale Turkish, plate `  iz 1234 ` is saved as `IZ 1234` and the
   PASS_RECORDED audit payload contains exactly that plate. Restore the original default
   locale in finally so the test does not contaminate other tests.
2. Existing trimming and lower-case payment input keep passing.
3. Null, empty and whitespace-only plates each throw IllegalArgumentException; the pass
   repository is never saved and the audit client is never called.
4. Existing fare, shift, unknown-class and payment-method tests retain their assertions.

Validation: Maven test for the backend with PostgreSQL and MongoDB provided by Docker.
The existing DashboardAggregationTest needs a separate northgate_toll_test database;
infrastructure setup must supply it and make its connection configurable if necessary.
Readiness of Compose and application HTTP endpoints is separate infrastructure evidence.
