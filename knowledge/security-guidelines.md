# Security Guidelines

## Authentication, Tokens, and Session Lifecycle

Implement authentication using industry-standard protocols such as OAuth2 and OpenID Connect with JSON Web Tokens (JWT). Sign tokens using robust asymmetric or HMAC algorithms (e.g., RS256, EdDSA, HS256) with securely rotated keys. Validate token signatures, issuer (`iss`), audience (`aud`), and expiration time (`exp`) on every request. Short-lived access tokens should be paired with revocable refresh tokens stored securely in HttpOnly, SameSite cookies or protected storage. Ensure logout flows explicitly revoke or blacklist active refresh tokens.

## Password Hashing and Cryptographic Best Practices

Store user passwords exclusively as salted cryptographic hashes computed with modern algorithms: Argon2id (recommended), bcrypt (with an adaptive work factor appropriate for hardware speeds), or PBKDF2 with SHA-256. Never store plaintext passwords or employ outdated hash algorithms like MD5 or SHA-1. Generate security-critical tokens (session IDs, password reset tokens, API keys) using cryptographically secure pseudorandom number generators (CSPRNG, such as `java.security.SecureRandom`, `System.Security.Cryptography.RandomNumberGenerator`, `crypto.randomBytes`, or Python's `secrets` module).

## Secrets Management, Environment Isolation, and Sanitization

Never commit secrets, credentials, API keys, database connection strings, or private keys to source control repositories. Load sensitive configuration values exclusively from environment variables or dedicated secret managers (e.g., Azure Key Vault, AWS Secrets Manager, HashiCorp Vault). Enforce strict filesystem boundaries: deny read access to `.env` and configuration files containing secrets, and reject symlink traversal outside the project directory. Sanitize all application logs, metrics, and distributed traces to guarantee that passwords, tokens, credit card numbers, and PII are never logged.

## Vulnerability Remediation, SCA, and Least Privilege

Adopt the principle of least privilege for database connection users, cloud service accounts, and microservice communication tokens. Maintain lockfiles (`package-lock.json`, `pom.xml`, `Directory.Packages.props`, `requirements.txt`) and run automated Software Composition Analysis (SCA) to detect outdated or vulnerable third-party dependencies. When a security finding or vulnerability is reported, apply surgical patches to remediate the flaw without weakening existing validation layers or disabling defensive controls.
