# PruebaNuevosIngresosBackend: protect order amount invariants

Repository: https://github.com/full-stack-dev-johncastrosanabria/PruebaNuevosIngresosBackend
Base: main, 73099ab3958e253dc1c1bca4f8fa648b77104772. Component: order-ms (Java 21).

Order.nuevo must reject nonpositive quantity and null, zero or negative unitPrice with
IllegalArgumentException. Keep valid-order behavior unchanged: calculate total using
unitPrice multiplied by quantity, rounded once to two decimal places with HALF_UP;
preserve the original unitPrice, initial PENDIENTE status, card metadata, timestamps,
and payment transition rules. Keep existing public method signatures and persistence
annotations. No changes to payment/Kafka semantics or HTTP validation are required.

Source: order-ms/src/main/java/com/prueba/orderms/domain/Order.java
Tests: order-ms/src/test/java/com/prueba/orderms/domain/OrderTest.java

## Acceptance tests

1. Quantity 0 and -1 each throw IllegalArgumentException.
2. Unit prices null, 0 and -0.01 each throw IllegalArgumentException.
3. Quantity 3 and unitPrice 10.333 yield totalAmount 31.00 while unitPrice remains 10.333.
4. Quantity 1 and unitPrice 0.005 yield totalAmount 0.01 (HALF_UP).
5. Existing creation and payment-transition tests remain unchanged and pass.

Use the existing JUnit 5 and AssertJ patterns. Validate the complete order-ms suite,
including its real PostgreSQL/Kafka integration tests, and payment-ms regression suite.
The declared Docker Compose is the infrastructure source. Tests requiring Docker must
actually execute; disabling Testcontainers does not satisfy acceptance.
