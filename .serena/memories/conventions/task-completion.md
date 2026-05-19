# Task Completion Checklist

## After completing a task:

### Go Backend
1. `make test` — all tests pass
2. `make lint` — no lint errors
3. `make build` — binaries compile
4. If DB changes: `make db-migrate` succeeds
5. Save checkpoint to Serena memory

### Python Service
1. `uv run pytest` — all tests pass
2. `uv run ruff check .` — no lint errors
3. `uv run ruff format --check .` — formatting correct
4. Health endpoint responds: `curl localhost:8081/healthz`

### NextJS Dashboard
1. `npm run build` — production build succeeds (no type errors)
2. `npm run test` — vitest passes
3. `npm run lint` — eslint clean
4. Dev server renders: `npm run dev` → check localhost:3500

### General
- Update Serena memory with checkpoint
- Ensure docker-compose still works if infra changed
- No secrets (.env files) committed
