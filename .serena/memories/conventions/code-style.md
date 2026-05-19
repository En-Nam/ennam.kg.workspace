# Code Style & Conventions

## Go Backend
- **Go 1.23** with standard library HTTP server (net/http, no framework)
- **Naming**: PascalCase exports, camelCase unexported, snake_case for YAML/JSON fields
- **Package structure**: `cmd/` (entry points), `internal/` (private packages by concern)
- **Error handling**: Wrap with `fmt.Errorf("context: %w", err)`, return early on error
- **Logging**: `log/slog` structured logging with CloudWatch integration
- **Config**: YAML files + env var overrides, pydantic-like validation in Go
- **Database**: Raw SQL with `database/sql` (no ORM), prepared statements
- **Testing**: Standard `testing` package, table-driven tests, `_test.go` suffix
- **Linting**: `golangci-lint`

## Python Service (Planned)
- **Python 3.12+** with `uv` package manager
- **Framework**: FastAPI (async)
- **Config**: pydantic-settings
- **HTTP client**: httpx (async)
- **Type hints**: Required everywhere
- **Testing**: pytest
- **Code style**: ruff (format + lint)

## NextJS Dashboard (Planned)
- **NextJS 15** with App Router
- **TypeScript strict mode**
- **Styling**: Tailwind CSS + shadcn/ui
- **State**: TanStack Query (server) + Zustand (client)
- **Components**: Functional with hooks, no class components
- **Testing**: Vitest + Playwright

## General
- Commit messages: imperative mood, concise
- No unnecessary comments — code should be self-documenting
- Each service has its own Dockerfile (multi-stage builds)
- Environment configs: development.yaml, staging.yaml, production.yaml
