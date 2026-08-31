# OWASP API Security Practices

## Broken Object Level Authorization and Access Control

Prevent Broken Object Level Authorization (BOLA / IDOR) by enforcing access control checks on every single request containing an object identifier. Never assume that possessing an identifier (such as a database ID, UUID, or GUID) grants permission to read, modify, or delete that resource. Derive authorization directly from the authenticated security principal or session token, and enforce user-scoped or tenant-scoped filters at the database query level. Return identical `404 Not Found` or `403 Forbidden` responses for unauthorized object lookups to prevent unauthorized entity existence enumeration.

## Broken Authentication and Sensitive Flow Protection

Protect authentication endpoints, password resets, and session creation against credential stuffing, brute force, and account enumeration. Return uniform response messages and identical HTTP response times for both existing and non-existing accounts during login and recovery requests. Password reset and verification tokens must be cryptographically random with high entropy, single-use, tied strictly to the target user account, and strictly bounded by short expiration windows. Implement account lockouts or progressive delays after consecutive failed authentication attempts.

## Injection, Mass Assignment, and Excessive Data Exposure

Prevent SQL, NoSQL, and Command Injection by exclusively using parameterized queries, prepared statements, or strongly typed Object-Relational Mappers (EF Core, Hibernate, SQLAlchemy). Avoid dynamic SQL concatenation with untrusted input under all circumstances. Prevent Mass Assignment vulnerabilities by binding incoming request payloads strictly to dedicated DTOs or ViewModels rather than binding directly to persistent database entities. Ensure API responses return only the fields explicitly declared in public contracts, omitting sensitive attributes such as password hashes, internal roles, and system metadata.

## Security Misconfiguration, CORS, and Rate Limiting

Secure API infrastructure by disabling default credentials, verbose stack traces, and unused HTTP methods. Configure Cross-Origin Resource Sharing (CORS) with explicitly allowed origins instead of wildcards (`*`) on authenticated endpoints. Enforce transport layer security with HTTPS and HTTP Strict Transport Security (HSTS) headers. Implement rate limiting and request payload size limits across all endpoints to prevent resource exhaustion and Denial of Service (DoS) attacks. Regularly scan dependencies for known Common Vulnerabilities and Exposures (CVEs).
