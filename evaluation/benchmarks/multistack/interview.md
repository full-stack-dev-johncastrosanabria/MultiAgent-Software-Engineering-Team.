# InterviewCleanApi: expose the existing low-stock query

Repository: https://github.com/full-stack-dev-johncastrosanabria/InterviewCleanApi
Base: main, c86d9705cf778c915c96e015bb1ff100c119f3b2. Component: solution root (.NET 10).

Expose GET /api/products/low-stock?threshold=10 to authenticated users. The threshold
defaults to 10 and must be positive. Return ProductResponse DTOs using the existing
IProductRepository.GetLowStockProductsAsync method, whose contract is Stock < threshold
ordered by Stock ascending. Empty results return HTTP 200 with an empty array.

Add GetLowStockAsync to IProductService and ProductService, preserving cancellation,
the repository query, MapToResponse, Result<T>, logging and existing error conventions.
Use Error.Validation for invalid thresholds and map to HTTP 400 in the controller.
Repository failures use the existing Problem/HTTP 500 convention. Preserve controller
authorization, CRUD behavior, entity schema and migrations.

Files: InterviewCleanApi.Application/Abstractions/IProductService.cs,
InterviewCleanApi.Infrastructure/Services/ProductService.cs,
InterviewCleanApi.Api/Controllers/ProductsController.cs,
InterviewCleanApi.Tests/ProductLowStockTests.cs (new).

## Acceptance tests

1. Positive threshold and cancellation token are delegated to the existing low-stock
   repository method; DTO mapping preserves every product field and returned ordering.
2. 0 and negative threshold return Error.Validation without calling the repository.
3. Empty repository results produce successful empty lists.
4. Repository exceptions produce a failed Result and HTTP 500 via the controller.
5. Controller default threshold is 10; success gives 200, validation failure gives 400.
6. Authenticated integration requests with threshold N exclude Stock == N and include
   Stock < N; unauthenticated requests return 401. Use the real MySQL test environment.

Use existing xUnit, Moq and FluentAssertions dependencies. Run dotnet test on the solution
against a fresh Docker MySQL schema prepared with existing EF migrations. Record any
existing Selenium tests that silently return separately from the endpoint evidence.
