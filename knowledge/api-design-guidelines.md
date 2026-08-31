# API Design Guidelines

## Resource and Endpoint Design

Model HTTP endpoints around clear domain resources using standard HTTP verbs (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`). URIs must use lowercase, hyphen-separated nouns in plural form (e.g., `/api/v1/user-profiles`, `/api/v1/orders/{id}/items`). Endpoints should return predictable HTTP status codes: `200 OK` or `201 Created` for successes, `204 No Content` for deletions, `400 Bad Request` for invalid input, `401 Unauthorized` for missing authentication, `403 Forbidden` for unauthorized resource access, `404 Not Found` for missing entities, and `409 Conflict` for state conflicts. Collection queries must implement deterministic ordering, default pagination (page/limit or cursor-based), and query parameter filtering.

## Input and Output Contracts

Validate data types, string formats, numeric ranges, and required fields at the application boundary before invoking domain handlers. Use strongly typed Data Transfer Objects (DTOs), Pydantic schemas, or C# records to decouple internal entities from the public wire contract. Format all error responses following the standard RFC 7807 `ProblemDetails` specification (containing `type`, `title`, `status`, `detail`, `instance`, and validation error dictionaries). Never expose internal stack traces, database column names, or raw framework exceptions to API consumers.

## Authorization, Rate Limiting, and Idempotency

Enforce authentication and permission checks on every non-public endpoint. Never trust unverified client-supplied identifiers in query parameters or request bodies; verify ownership against the authenticated security context or token claims. Protect mutating operations (such as payment processing or order submission) with client-supplied `Idempotency-Key` headers stored in an atomic cache. Apply rate limiting and throttling to sensitive endpoints (login, password reset, payment processing) to prevent abuse and denial of service.

## Observability, Versioning, and Backward Compatibility

Include unique correlation identifiers (`X-Correlation-ID` or `TraceParent`) in request and response headers to enable end-to-end distributed tracing across microservices. Maintain backward compatibility when updating existing endpoints by making new fields optional and avoiding breaking changes to response shapes. When introducing breaking changes, declare explicit API versioning (via URI prefix `/api/v2/` or Accept headers) and define deprecation timelines. Document all endpoints, parameters, request bodies, and responses using OpenAPI / Swagger specifications.
