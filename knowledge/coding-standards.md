# Coding Standards

## C# and .NET 10 Development Standards

Adhere to modern C# 12 / .NET 10 idioms and Clean Architecture conventions. Use `record` types for immutable DTOs, messages, and value objects. Structure ASP.NET Core endpoints using either Minimal APIs with typed endpoint filters or controllers with explicit route attributes. Register services into the dependency injection container with appropriate lifecycles (`Scoped` for DbContext and repositories, `Singleton` for stateless utilities, `Transient` for lightweight operations). For data access with Entity Framework Core, use strongly typed `DbSet<T>`, configure entities using `IEntityTypeConfiguration<T>` in separate mapping classes, avoid client evaluation by writing clean LINQ queries, and execute async I/O with `SaveChangesAsync(cancellationToken)`.

## Java 21 and Spring Boot 3 Standards

Leverage modern Java 21 features including pattern matching, sealed interfaces, and `record` types for data carrier objects. In Spring Boot 3 applications, use constructor injection with `@RequiredArgsConstructor` (or explicit constructors) instead of field injection. Separate domain services from Spring Data JPA repositories and presentation controllers. Use `@RestControllerAdvice` with `@ExceptionHandler` for centralized exception translation into RFC 7807 problem details. Validate incoming payloads with Jakarta Bean Validation (`@Valid`, `@NotNull`, `@Size`, `@Pattern`). Keep entity mutations inside declarative `@Transactional` boundaries, avoiding lazy initialization issues by utilizing `@EntityGraph` or explicit fetch joins.

## TypeScript and Modern Frontend Standards

Enforce strict typing in TypeScript projects (`strict: true`, no `any`). For React 18/19 applications, author modular functional components using React Hooks (`useState`, `useReducer`, `useEffect`, `useMemo`), validate props with TypeScript interfaces, and manage asynchronous server state with TanStack Query. For Angular 21, use standalone components, signals for fine-grained reactivity, and typed reactive forms. For Vue 3, use the Composition API with `<script setup lang="ts">`. Keep UI state isolated from business logic by encapsulating HTTP client calls into dedicated service modules. Validate runtime payloads using schema libraries (such as Zod or Yup) before processing.

## Python and General Software Craftsmanship

In Python applications (FastAPI, Flask), enforce strict type hints with Python 3.10+ syntax and Pydantic v2 data models. Use application factories, dependency injection with `Depends()`, and structured configuration settings with `pydantic-settings`. Across all languages: implement bounded, surgical changes that satisfy the specification without performing unrelated refactors; respect existing repository conventions and naming patterns; avoid circular dependencies; and ensure all file modifications remain within the authorized project workspace without touching sensitive environment files.
