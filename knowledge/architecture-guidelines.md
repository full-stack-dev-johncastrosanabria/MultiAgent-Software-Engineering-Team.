# Architecture Guidelines

## Clean Architecture and Domain-Driven Design

Structure applications with clear dependency direction where domain entities and business rules remain isolated from frameworks, databases, and UI components. In Clean / Hexagonal / Onion architecture, the Domain Layer defines core entities, value objects, and repository interfaces without depending on external libraries. The Application Layer orchestrates use cases, commands, queries, and business workflows. The Infrastructure Layer implements persistence (Entity Framework Core, Spring Data JPA, SQLAlchemy, Mongo repositories), messaging clients, and third-party integrations. The Presentation / Web Layer hosts REST controllers, Minimal APIs, or GraphQL resolvers. Dependencies must point strictly inward toward the domain core.

## Microservices and Bounded Contexts

Decompose distributed systems around cohesive business capabilities and bounded contexts. Each microservice must own its domain data model and persistence store to avoid tight database-level coupling. Service communication should prefer asynchronous messaging for state propagation and lightweight REST / gRPC contracts for real-time queries. Keep service boundaries explicit with shared DTO contracts or schema registries. Isolate failure domains using circuit breakers, exponential backoff, and distributed tracing. When coordinating distributed state, avoid distributed two-phase commits in favor of eventual consistency and saga choreography or orchestration.

## Event-Driven Architecture and Messaging

Model asynchronous workflows around explicit domain events. When using message brokers like Apache Kafka, RabbitMQ, or cloud queues, ensure event payloads contain the necessary immutable context without leaking internal database schemas. Producers must guarantee delivery using patterns like the Transactional Outbox to prevent inconsistent state between database writes and message publication. Consumers must be idempotent by validating message identifiers against processed event logs. Configure appropriate partition keys to maintain strict ordering per entity, and route unrecoverable processing failures to Dead Letter Queues (DLQ) with alertable observability.

## Data, Dependencies, and Operational Resilience

Isolate persistence mechanisms behind repository interfaces and abstract data access. Support relational databases (PostgreSQL, MySQL, SQLite) with migration tools and document databases (MongoDB) with explicit schema validation. Scope database transactions tightly around single use case boundaries to prevent long-lived locks and connection pool starvation. External service integrations must specify deterministic timeouts, retry limits, and fallback strategies. Ensure health checks verify underlying dependencies before traffic is routed. Architectural decisions must be grounded in verified repository structure and explicit risk analysis.
