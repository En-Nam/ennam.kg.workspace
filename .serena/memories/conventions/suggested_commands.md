# Suggested Commands — Ennam KG Platform

## Go Backend (ennam.kg.go/)
```bash
# Development
make dev              # Start PostgreSQL + kg-server (docker-compose up)
make dev-down         # Stop all services
make dev-logs         # Follow logs
make dev-restart      # Restart services

# Database
make db-up            # Start PostgreSQL only
make db-down          # Stop PostgreSQL
make db-reset         # Destroy + reinit database
make db-shell         # Open psql shell
make db-migrate       # Run pending migrations (up)
make db-migrate-down  # Roll back last migration
make db-migrate-version  # Print current version

# Build & Test
make build            # Build kg-server, kg-bridge, kg-migrate
make test             # go test ./... -v -race -count=1
make lint             # golangci-lint run ./...
make clean            # Remove bin/ tmp/ + docker volumes

# Direct commands
go build -o bin/kg-server ./cmd/kg-server/
go build -o bin/kg-bridge ./cmd/kg-bridge/
go run ./cmd/kg-server/            # Run API server directly
go run ./cmd/kg-bridge/ serve      # Run MCP bridge
go run ./cmd/kg-migrate/ up        # Run migrations
```

## Python Service (ennam.kg.python/)
```bash
uv sync                            # Install dependencies
uv sync --no-dev                   # Production only
uv run uvicorn ennam_kg.main:app --reload --port 8081  # HTTP server
uv run python -m ennam_kg.worker   # Queue worker
uv run pytest                      # All 89 tests
uv run pytest -v                   # Verbose
uv run ruff check src/ tests/      # Lint
uv run ruff format src/ tests/     # Format
```

## NextJS Dashboard (ennam.kg.next/)
```bash
npm run dev                # Dev server (port 3500)
npm run build              # Production build (standalone)
npm run start              # Start production server
npm run lint               # ESLint
npx shadcn@latest add [component-name]  # Add shadcn/ui components
```

## Unified Docker (root docker-compose.yml)
```bash
docker compose up -d       # Start all 6 services
docker compose up -d --build  # Rebuild and start
docker compose logs -f     # Follow all logs
docker compose logs -f kg-server  # Follow specific service
docker compose ps          # Check status
docker compose down        # Stop all
docker compose down -v     # Stop and remove data
```

## Services & Ports
| Service | Port | URL |
|---------|------|-----|
| Go API | 8080 | http://localhost:8080 |
| Python Indexer | 8081 | http://localhost:8081 |
| Dashboard | 3500 | http://localhost:3500 |
| PostgreSQL | 5432 | localhost:5432 |
| Redis | 6379 | localhost:6379 |
