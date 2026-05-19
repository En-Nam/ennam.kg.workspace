#!/usr/bin/env bash
# Ennam Knowledge Graph — Demo Seed Data
# Seeds 3 projects (Go API, NextJS Dashboard, Python Indexer) with realistic
# decisions, concepts, architecture, requirements, tasks, and discoveries
# that reflect the actual Ennam KG platform.
#
# Usage:
#   ./scripts/seed-demo.sh                          # Use defaults
#   API_URL=http://localhost:8080 ./scripts/seed-demo.sh
#
# Prerequisites:
#   - Go API running and healthy
#   - curl installed

set -uo pipefail

API_URL="${API_URL:-http://127.0.0.1:8080}"
API_KEY="${API_KEY:-ennam_kg_danny_test_b13b555c5533e45df5d613d8ab94500f}"
AUTH="Authorization: Bearer $API_KEY"
CT="Content-Type: application/json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

CREATED=0
FAILED=0
EDGE_CREATED=0
EDGE_FAILED=0

# --------------------------------------------------------------------------
# Helper: create a node, capture its ID
# --------------------------------------------------------------------------
create_node() {
  local var_name="$1"
  local json="$2"
  local label="$3"

  local resp
  resp=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/api/v1/nodes" \
    -H "$AUTH" -H "$CT" -d "$json")

  local http_code
  http_code=$(echo "$resp" | tail -1)
  local body
  body=$(echo "$resp" | sed '$d')

  if [[ "$http_code" == "201" ]]; then
    local id
    id=$(echo "$body" | grep -o '"id":"[^"]*"' | head -1 | sed 's/"id":"//;s/"//')
    if [[ -n "$id" ]]; then
      eval "$var_name='$id'"
      printf "  ${GREEN}✓${NC} %-60s ${CYAN}%s${NC}\n" "$label" "$id"
      CREATED=$((CREATED + 1))
      return 0
    fi
  fi

  printf "  ${RED}✗${NC} %-60s ${RED}%s${NC}\n" "$label" "$http_code"
  echo "    $body" | head -1
  FAILED=$((FAILED + 1))
  eval "$var_name=''"
  return 1
}

# --------------------------------------------------------------------------
# Helper: create an edge between two nodes
# --------------------------------------------------------------------------
create_edge() {
  local project_id="$1"
  local source_id="$2"
  local target_id="$3"
  local relationship="$4"
  local label="$5"

  if [[ -z "$source_id" || -z "$target_id" ]]; then
    printf "  ${YELLOW}⊘${NC} %-60s ${YELLOW}skipped (missing node)${NC}\n" "$label"
    return 0
  fi

  local json
  json=$(cat <<EJSON
{
  "project_id": "$project_id",
  "source_id": "$source_id",
  "target_id": "$target_id",
  "relationship": "$relationship",
  "created_by": "seed-script"
}
EJSON
)

  local resp
  resp=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/api/v1/edges" \
    -H "$AUTH" -H "$CT" -d "$json")

  local http_code
  http_code=$(echo "$resp" | tail -1)

  if [[ "$http_code" == "201" ]]; then
    printf "  ${GREEN}→${NC} %-60s\n" "$label"
    EDGE_CREATED=$((EDGE_CREATED + 1))
  else
    local body
    body=$(echo "$resp" | sed '$d')
    printf "  ${RED}→${NC} %-60s ${RED}%s${NC}\n" "$label" "$http_code"
    echo "    $body" | head -1
    EDGE_FAILED=$((EDGE_FAILED + 1))
  fi
}

# --------------------------------------------------------------------------
# Preflight check
# --------------------------------------------------------------------------
echo ""
printf "${CYAN}══════════════════════════════════════════════════════════════${NC}\n"
printf "${CYAN}  Ennam Knowledge Graph — Demo Seed Data${NC}\n"
printf "${CYAN}══════════════════════════════════════════════════════════════${NC}\n"
echo ""

printf "API: $API_URL ... "
if curl -sf "$API_URL/readyz" > /dev/null 2>&1; then
  printf "${GREEN}ready${NC}\n"
else
  printf "${RED}not ready${NC}\n"
  echo "Start the API first: docker compose up -d"
  exit 1
fi

# ==========================================================================
# STEP 1: Create 3 projects
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 1: Projects ━━━${NC}\n"

# Check if projects exist or create them
PROJECT_GO=""
PROJECT_NEXT=""
PROJECT_PYTHON=""

create_project() {
  local var_name="$1"
  local name="$2"
  local desc="$3"
  local repo="$4"

  local resp
  resp=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/api/v1/projects" \
    -H "$AUTH" -H "$CT" -d "{\"name\":\"$name\",\"description\":\"$desc\",\"repo_url\":\"$repo\"}")

  local http_code
  http_code=$(echo "$resp" | tail -1)
  local body
  body=$(echo "$resp" | sed '$d')

  if [[ "$http_code" == "201" || "$http_code" == "200" ]]; then
    local id
    id=$(echo "$body" | grep -o '"id":"[^"]*"' | head -1 | sed 's/"id":"//;s/"//')
    if [[ -n "$id" ]]; then
      eval "$var_name='$id'"
      printf "  ${GREEN}✓${NC} %-40s ${CYAN}%s${NC}\n" "$name" "$id"
      return 0
    fi
  fi

  # Try listing existing projects
  local list_resp
  list_resp=$(curl -s "$API_URL/api/v1/projects" -H "$AUTH" 2>/dev/null)
  local id
  id=$(echo "$list_resp" | grep -o "\"id\":\"[^\"]*\"" | head -1 | sed 's/"id":"//;s/"//' || true)
  if [[ -n "$id" ]]; then
    eval "$var_name='$id'"
    printf "  ${GREEN}✓${NC} %-40s ${CYAN}%s${NC} (existing)\n" "$name" "$id"
    return 0
  fi

  printf "  ${RED}✗${NC} %-40s ${RED}%s${NC}\n" "$name" "$http_code"
  echo "    $body" | head -1
  eval "$var_name=''"
  return 1
}

# Use the existing project for Go, create new ones for Next and Python
# First, let's use the existing dev-project and create via SQL for reliability
echo "  Using existing project + creating via DB..."

# Create projects via psql (most reliable)
PROJECT_GO="a0000000-0000-0000-0000-000000000001"
PROJECT_NEXT="a0000000-0000-0000-0000-000000000002"
PROJECT_PYTHON="a0000000-0000-0000-0000-000000000003"

docker compose exec -T postgres psql -U ennam_kg -d ennam_kg -q <<SQL
-- Update existing project
UPDATE projects SET name = 'ennam-kg-go', description = 'Go REST API + MCP Bridge', repo_url = 'https://github.com/En-Nam/ennam.kg.go' WHERE id = '$PROJECT_GO';

-- Create NextJS project
INSERT INTO projects (id, name, description, repo_url)
VALUES ('$PROJECT_NEXT', 'ennam-kg-next', 'NextJS Dashboard', 'https://github.com/En-Nam/ennam.kg.next')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description;

-- Create Python project
INSERT INTO projects (id, name, description, repo_url)
VALUES ('$PROJECT_PYTHON', 'ennam-kg-python', 'Python Code Indexer', 'https://github.com/En-Nam/ennam.kg.python')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description;

-- Grant danny access to all 3 projects
UPDATE api_keys SET project_ids = ARRAY['$PROJECT_GO', '$PROJECT_NEXT', '$PROJECT_PYTHON']::uuid[]
WHERE developer_name = 'danny';
SQL

printf "  ${GREEN}✓${NC} ennam-kg-go      ${CYAN}$PROJECT_GO${NC}\n"
printf "  ${GREEN}✓${NC} ennam-kg-next    ${CYAN}$PROJECT_NEXT${NC}\n"
printf "  ${GREEN}✓${NC} ennam-kg-python  ${CYAN}$PROJECT_PYTHON${NC}\n"

# ==========================================================================
# STEP 2: Go API — Decisions
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 2: Go API — Decisions ━━━${NC}\n"

create_node GO_D1 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "decision",
  "title": "Use PostgreSQL with JSONB for knowledge storage",
  "properties": {
    "context": "The knowledge graph needs a storage engine that supports typed nodes, full-text search, and flexible schema. Graph databases like Neo4j were considered but add operational complexity. We need recursive traversal (CTEs) and JSONB for type-specific properties.",
    "rationale": "PostgreSQL provides JSONB for flexible properties, pg_trgm for fuzzy text search, recursive CTEs for graph traversal, and UUID primary keys. It runs on AWS RDS without extensions like AGE. The team has deep PostgreSQL experience.",
    "alternatives": ["Neo4j — purpose-built but requires separate infra", "MongoDB — flexible schema but weak relational queries", "DynamoDB — serverless but no joins or CTEs"],
    "impact": "All data access uses database/sql with lib/pq. Node properties are stored as JSONB. Graph queries use recursive CTEs instead of native graph traversal.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: PostgreSQL with JSONB"

create_node GO_D2 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "decision",
  "title": "Config-driven validation with Gate 1 and Gate 2",
  "properties": {
    "context": "Knowledge nodes have type-specific schemas (decisions need rationale, tasks need status). Validation rules change frequently as we add node types. Hardcoded validation creates tight coupling between handlers and business rules.",
    "rationale": "A single config.yaml defines all node schemas, required fields, allowed enum values, and completeness rules. Gate 1 checks schema conformance (returns 400). Gate 2 checks completeness rules per scope (returns 422 with detailed violations). This separation allows non-code changes to validation.",
    "alternatives": ["Hardcoded struct tags — Go-native but rigid", "JSON Schema — standard but verbose for our use case", "Protocol Buffers — good for contracts but overkill internally"],
    "impact": "config/config.yaml is the single source of truth. Adding a new node type requires only config changes, not code changes. Gate 2 violations are non-blocking warnings at most scopes.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: Config-driven Gate 1 + Gate 2"

create_node GO_D3 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "decision",
  "title": "Fire-and-forget Redis queue for async indexing",
  "properties": {
    "context": "When a node is created via the API, the Python indexing service may need to update code references. This should not block the API response. We need a decoupled async messaging pattern.",
    "rationale": "Redis LPUSH/BRPOP provides a simple, reliable queue without adding Kafka or RabbitMQ complexity. The publisher uses raw RESP protocol (no go-redis dependency) and never fails the HTTP response. Falls back to a noop publisher if Redis is unavailable.",
    "alternatives": ["SQS — managed but adds AWS coupling for local dev", "Kafka — powerful but massive overkill", "Direct HTTP callback — synchronous, couples services"],
    "impact": "Node creation handlers call pub.Publish() after successful store. The queue package is 150 lines of raw RESP. Python worker consumes via BRPOP.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: Fire-and-forget Redis queue"

create_node GO_D4 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "decision",
  "title": "MCP stdio bridge as separate binary",
  "properties": {
    "context": "Claude Code needs to interact with the knowledge graph via MCP tools (kg_store_decision, kg_search, etc). MCP uses stdio transport. The REST API uses HTTP. We need a bridge between these two protocols.",
    "rationale": "A separate kg-bridge binary translates 25 MCP tool calls into HTTP API requests. Running as a separate process isolates MCP stdio from the HTTP server lifecycle. The bridge auto-injects node_type based on which kg_store_* tool is called, simplifying the MCP schema.",
    "alternatives": ["Embed MCP server in kg-server — mixes transports", "Use HTTP-based MCP — not supported by Claude Code yet", "Direct DB access from bridge — bypasses validation"],
    "impact": "Two binaries share internal/ packages. Bridge depends on API being available. MCP tool definitions mirror API endpoints 1:1.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: MCP stdio bridge"

create_node GO_D5 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "decision",
  "title": "Layered architecture: Handler → Service → Store",
  "properties": {
    "context": "The Go API needs clear separation between HTTP concerns, business logic, and data access. Handlers should not contain SQL. Stores should not know about HTTP status codes. Business rules (validation, authorization) need a dedicated layer.",
    "rationale": "Three-layer architecture keeps each layer focused: Handlers marshal JSON and map errors to HTTP codes. Services enforce Gate 1/2 validation, edge whitelist rules, and cross-project authorization. Stores execute pure SQL via database/sql with no business logic.",
    "alternatives": ["Two-layer (handler+store) — simpler but mixes concerns", "Clean Architecture hexagonal — too many abstractions for our scale", "CQRS — overkill without event sourcing"],
    "impact": "All dependency injection happens in cmd/kg-server/main.go. Each node type has its own handler file but they all delegate to NodeService. Stores support both direct calls and TxBeginner transactions.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: Handler → Service → Store"

# ==========================================================================
# STEP 3: Go API — Concepts
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 3: Go API — Concepts ━━━${NC}\n"

create_node GO_C1 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "concept",
  "title": "Knowledge Node",
  "properties": {
    "name": "Knowledge Node",
    "definition": "The fundamental unit of information in the knowledge graph. Each node has a type (decision, concept, requirement, task, architecture, discovery), a title, properties stored as JSONB, and lifecycle status. Nodes are scoped to a project and versioned on update.",
    "domain": "knowledge-graph",
    "aliases": ["node", "KG node", "graph node"]
  },
  "created_by": "danny"
}' "Concept: Knowledge Node"

create_node GO_C2 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "concept",
  "title": "Edge Whitelist",
  "properties": {
    "name": "Edge Whitelist",
    "definition": "A strict configuration-driven rule set that defines which edge types are allowed between which node types. For example, a decision can relate_to a concept but a concept cannot impact a task. Edges not in the whitelist are rejected at Gate 1 validation. Some edges allow cross-project references.",
    "domain": "validation",
    "aliases": ["edge rules", "relationship whitelist"]
  },
  "created_by": "danny"
}' "Concept: Edge Whitelist"

create_node GO_C3 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "concept",
  "title": "Completeness Scope",
  "properties": {
    "name": "Completeness Scope",
    "definition": "A context marker that determines which Gate 2 completeness rules apply. Examples: session_end requires all active tasks to have descriptions, pre_commit requires decisions to have rationale, task_complete requires related requirements to exist. Non-blocking violations are returned as warnings.",
    "domain": "validation",
    "aliases": ["scope", "work scope", "validation scope"]
  },
  "created_by": "danny"
}' "Concept: Completeness Scope"

create_node GO_C4 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "concept",
  "title": "Developer Identity",
  "properties": {
    "name": "Developer Identity",
    "definition": "The authenticated context extracted from a valid API key during request processing. Contains the developer name, role (admin/developer/agent/viewer), allowed project IDs, and default project. Injected into the request context by the auth middleware and used by handlers for authorization decisions.",
    "domain": "authentication",
    "aliases": ["auth context", "API key identity", "caller identity"]
  },
  "created_by": "danny"
}' "Concept: Developer Identity"

create_node GO_C5 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "concept",
  "title": "Flat Response Envelope",
  "properties": {
    "name": "Flat Response Envelope",
    "definition": "The standard API response format used by all endpoints: {nodes[], edges[], metadata{}}. Search results include total_count, limit, offset. Single-node responses wrap in {node: {}}. This flat structure avoids deeply nested JSON and makes client parsing simpler.",
    "domain": "api-design",
    "aliases": ["response envelope", "API response format"]
  },
  "created_by": "danny"
}' "Concept: Flat Response Envelope"

# ==========================================================================
# STEP 4: Go API — Architecture
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 4: Go API — Architecture ━━━${NC}\n"

create_node GO_A1 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "architecture",
  "title": "REST API Endpoint Catalog",
  "properties": {
    "arch_type": "api_contract",
    "content": "## Node Operations\n- POST /api/v1/nodes — Create node (unified, all types)\n- POST /api/v1/nodes/{type} — Create node (typed shorthand)\n- GET /api/v1/nodes/{id} — Get node by ID\n- PUT /api/v1/nodes/{id} — Update node\n- POST /api/v1/nodes/{id}/deprecate — Deprecate node\n\n## Search & Graph\n- GET/POST /api/v1/search — Full-text search with filters\n- GET /api/v1/nodes/{id}/neighbors — Get 1-hop neighbors\n- GET /api/v1/nodes/{id}/traverse — Recursive graph traversal\n\n## Edges\n- POST /api/v1/edges — Create edge (with whitelist validation)\n\n## Sessions\n- POST /api/v1/sessions — Start session\n- POST /api/v1/sessions/{id}/end — End session\n- GET /api/v1/sessions/{id} — Get session\n\n## Auth\n- POST /api/v1/api-keys — Create API key\n- GET /api/v1/api-keys — List keys\n- POST /api/v1/api-keys/{id}/revoke — Revoke key",
    "content_format": "markdown"
  },
  "created_by": "danny"
}' "Architecture: REST API Catalog"

create_node GO_A2 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "architecture",
  "title": "Database Schema — knowledge_nodes table",
  "properties": {
    "arch_type": "data_model",
    "content": "## knowledge_nodes\n| Column | Type | Description |\n|--------|------|-------------|\n| id | UUID PK | Auto-generated |\n| project_id | UUID FK→projects | Required |\n| node_type | TEXT CHECK | decision/concept/requirement/task/architecture/discovery |\n| title | TEXT | Human-readable title |\n| status | TEXT | active/deprecated/superseded |\n| properties | JSONB | Type-specific fields |\n| scope | TEXT | Work scope context |\n| version | INTEGER | Auto-incremented on update |\n| change_reason | TEXT | Required on update |\n| created_by | TEXT | Developer/agent name |\n| session_id | TEXT | Optional session reference |\n| created_at | TIMESTAMPTZ | Auto |\n| updated_at | TIMESTAMPTZ | Auto via trigger |\n\n## Indexes\n- project_id, node_type (composite)\n- properties (GIN for JSONB queries)\n- title (GIN pg_trgm for fuzzy search)\n- created_at DESC",
    "content_format": "markdown"
  },
  "created_by": "danny"
}' "Architecture: knowledge_nodes schema"

create_node GO_A3 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "architecture",
  "title": "Composition Root Pattern",
  "properties": {
    "arch_type": "pattern",
    "content": "All dependency injection happens in cmd/kg-server/main.go:\n\n1. Load config (YAML + env vars)\n2. Setup logging (slog + optional CloudWatch)\n3. Connect database (sql.Open + pool config)\n4. Run migrations (auto in dev)\n5. Create queue publisher (Redis or noop)\n6. Wire stores → services → handlers\n7. Build router with middleware chain\n8. Start HTTP server with graceful shutdown\n\nMiddleware chain (outermost first):\nRequestID → Recovery → Metrics → Logging → Auth (protected routes only) → Handler",
    "content_format": "markdown"
  },
  "created_by": "danny"
}' "Architecture: Composition Root"

# ==========================================================================
# STEP 5: Go API — Requirements, Tasks, Discoveries
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 5: Go API — Requirements & Tasks ━━━${NC}\n"

create_node GO_R1 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "requirement",
  "title": "API key authentication for all protected endpoints",
  "properties": {
    "req_id": "REQ-001",
    "description": "All /api/v1/* endpoints must require a valid API key via Authorization: Bearer header. Keys are SHA-256 hashed in the database. Health endpoints (/healthz, /readyz) are exempt. Invalid or revoked keys return 401.",
    "acceptance_criteria": ["Bearer token extracted from Authorization header", "SHA-256 hash lookup in api_keys table", "Revoked keys rejected", "Health endpoints exempt", "Developer identity injected into context"],
    "priority": "critical",
    "status": "completed"
  },
  "created_by": "danny"
}' "Requirement: API key auth"

create_node GO_R2 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "requirement",
  "title": "Node CRUD with type-specific validation",
  "properties": {
    "req_id": "REQ-002",
    "description": "Support create, read, update, and deprecate operations for 6 node types: decision, concept, requirement, task, architecture, discovery. Each type has specific required fields and validation rules defined in config.yaml. Gate 1 validates schema, Gate 2 validates completeness per scope.",
    "acceptance_criteria": ["POST /api/v1/nodes creates any node type", "Properties validated per config.yaml schema", "Gate 1 returns 400 for invalid fields", "Gate 2 returns 422 for incomplete nodes", "Version auto-incremented on update"],
    "priority": "critical",
    "status": "completed"
  },
  "created_by": "danny"
}' "Requirement: Node CRUD"

create_node GO_T1 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "task",
  "title": "Implement recursive graph traversal API",
  "properties": {
    "task_id": "TASK-001",
    "description": "Add GET /api/v1/nodes/{id}/traverse endpoint that performs recursive CTE-based graph traversal up to configurable depth. Support direction (outgoing/incoming/both) and optional edge type filter.",
    "status": "completed",
    "assignee": "claude-code",
    "branch": "feat/graph-traversal"
  },
  "created_by": "danny"
}' "Task: Graph traversal API"

create_node GO_T2 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "task",
  "title": "Add CloudWatch metrics publisher",
  "properties": {
    "task_id": "TASK-002",
    "description": "Publish API request metrics (latency, status codes, node operations) to AWS CloudWatch. Metrics collector is always active; publisher is optional and configured per environment. Fires every 60 seconds.",
    "status": "completed",
    "assignee": "claude-code"
  },
  "created_by": "danny"
}' "Task: CloudWatch metrics"

create_node GO_V1 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "discovery",
  "title": "golang-migrate Close() kills shared DB connection",
  "properties": {
    "description": "When using postgres.WithInstance(db, ...) to create a golang-migrate migrator, calling m.Close() closes both the source AND the shared *sql.DB connection pool. This caused all subsequent API requests to fail with sql: database is closed after migrations ran at startup.",
    "category": "bug",
    "severity": "critical",
    "resolved": true,
    "resolution": "Removed defer m.Close() calls from all MigrateUp/MigrateDown functions. The DB lifecycle is managed by the caller in main.go. The file source is garbage-collected."
  },
  "created_by": "danny"
}' "Discovery: migrate.Close() bug"

create_node GO_V2 '{
  "project_id": "'$PROJECT_GO'",
  "node_type": "discovery",
  "title": "Air hot-reload v1.64+ requires Go 1.25+",
  "properties": {
    "description": "The air hot-reload tool version 1.64.5 (latest) requires Go >= 1.25, but the project uses Go 1.23. Installing air@latest in the Dockerfile causes build failures in development mode. The error is not clear — it just fails to install.",
    "category": "edge_case",
    "severity": "medium",
    "resolved": true,
    "resolution": "Pinned air to v1.61.7 which supports Go 1.23. Added fallback CMD: sh -c air ... || go run ./cmd/kg-server/ so development works even without air."
  },
  "created_by": "danny"
}' "Discovery: Air version compat"

# ==========================================================================
# STEP 6: NextJS Dashboard — Decisions & Architecture
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 6: NextJS Dashboard ━━━${NC}\n"

create_node NX_D1 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "decision",
  "title": "BFF proxy pattern — never expose Go API to browser",
  "properties": {
    "context": "The NextJS dashboard needs to call the Go API. The API key must remain server-side. CORS between localhost:3000 and localhost:8080 adds complexity. We need a clean pattern for API access.",
    "rationale": "A catch-all API route (/api/kg/[...path]/route.ts) proxies all requests to the Go API, injecting the API key server-side. The browser only talks to NextJS. This eliminates CORS issues, hides the API key, and provides a natural place for response transformation.",
    "alternatives": ["Direct browser-to-API with CORS — exposes API key", "GraphQL gateway — too much abstraction", "Server components only — limits interactivity"],
    "impact": "All client-side data fetching goes through /api/kg/* routes. The GO_API_URL environment variable is server-side only. TanStack Query hooks call the BFF, not the Go API directly.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: BFF proxy pattern"

create_node NX_D2 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "decision",
  "title": "Cytoscape.js for graph visualization with dynamic import",
  "properties": {
    "context": "The dashboard needs interactive graph visualization for the knowledge graph. The library must handle 10K+ nodes, support multiple layouts, and work with React/NextJS. SSR compatibility is required.",
    "rationale": "Cytoscape.js is purpose-built for graph visualization with excellent layout algorithms (cola, dagre, cose). It handles large graphs efficiently. Dynamic import via useEffect avoids SSR crashes since Cytoscape requires window/DOM. Layout extensions are also dynamically registered.",
    "alternatives": ["D3.js force-directed — lower-level, more work", "vis.js — less maintained, fewer layouts", "react-flow — designed for flowcharts, not knowledge graphs"],
    "impact": "Graph component is lazy-loaded. KnowledgeGraph component exposes methods via DOM element. Node colors are coded by type: decision=blue, function=green, class=purple, concept=amber.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: Cytoscape.js graph viz"

create_node NX_D3 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "decision",
  "title": "TanStack Query for all data fetching with staleTime=60s",
  "properties": {
    "context": "The dashboard has many components that need the same data (nodes, sessions, search results). Re-fetching on every render wastes bandwidth. We need a caching and state management solution for server data.",
    "rationale": "TanStack Query provides automatic caching, deduplication, background refetching, and optimistic updates. With staleTime=60s and refetchOnWindowFocus=false, the dashboard feels responsive while keeping data reasonably fresh. Query keys follow [resource, id, filters] convention.",
    "alternatives": ["SWR — simpler but fewer features", "Redux Toolkit Query — heavier, adds Redux", "Server Components only — limits interactive features"],
    "impact": "All hooks in src/hooks/ use TanStack Query. QueryClient is provided at the root layout. Data fetching is declarative — components just call useNodes() or useSearch().",
    "status": "accepted"
  },
  "created_by": "danny"
}' "Decision: TanStack Query"

create_node NX_C1 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "concept",
  "title": "BFF Proxy",
  "properties": {
    "name": "BFF Proxy",
    "definition": "Backend-For-Frontend proxy implemented as a NextJS API route (/api/kg/[...path]/route.ts). Forwards all HTTP methods (GET, POST, PUT, DELETE) to the Go API, injecting the API key from the server-side session or environment variable. The browser never communicates directly with the Go API.",
    "domain": "api-design",
    "aliases": ["API proxy", "backend proxy", "catch-all route"]
  },
  "created_by": "danny"
}' "Concept: BFF Proxy"

create_node NX_C2 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "concept",
  "title": "Project Context",
  "properties": {
    "name": "Project Context",
    "definition": "A React context (ProjectProvider) that holds the currently selected project ID. All TanStack Query hooks use this context to scope their queries. The ProjectSwitcher component in the sidebar changes the active project, which triggers refetching of all data.",
    "domain": "state-management",
    "aliases": ["project scope", "active project"]
  },
  "created_by": "danny"
}' "Concept: Project Context"

create_node NX_A1 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "architecture",
  "title": "Dashboard Page Architecture",
  "properties": {
    "arch_type": "diagram",
    "content": "## Route Structure\n```\nsrc/app/\n├── (auth)/login/       → Login form + server action\n├── (dashboard)/\n│   ├── page.tsx        → Overview (stats, activity)\n│   ├── decisions/      → Decision timeline with filters\n│   ├── agents/         → Agent session timeline\n│   ├── graph/          → Cytoscape.js interactive viz\n│   ├── code-map/       → Module/function tree view\n│   ├── impact/         → Blast radius analysis\n│   ├── metrics/        → Platform stats charts\n│   └── settings/       → Config, users, API keys\n└── api/kg/[...path]/   → BFF proxy → Go API\n```\n\n## Data Flow\nClient Component → TanStack Query hook → /api/kg/* → Go API\n\n## Auth Flow\nLogin form → server action → iron-session cookie → session middleware",
    "content_format": "markdown"
  },
  "created_by": "danny"
}' "Architecture: Dashboard pages"

create_node NX_T1 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "task",
  "title": "Implement interactive graph page with Cytoscape",
  "properties": {
    "task_id": "TASK-010",
    "description": "Build the /graph page with interactive Cytoscape.js visualization. Includes: 5 layout algorithms (cola, dagre, cose, circle, grid), node type filtering, search highlighting, click-to-inspect side panel, PNG export. Cytoscape must be dynamically imported to avoid SSR issues.",
    "status": "completed",
    "assignee": "claude-code"
  },
  "created_by": "danny"
}' "Task: Graph visualization page"

create_node NX_T2 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "task",
  "title": "Build decision log timeline with status filtering",
  "properties": {
    "task_id": "TASK-011",
    "description": "Create the /decisions page showing architectural decisions in a timeline view. Support filtering by status (proposed/accepted/superseded/deprecated). Each card shows title, rationale preview, status badge, and creation date.",
    "status": "completed",
    "assignee": "claude-code"
  },
  "created_by": "danny"
}' "Task: Decision log timeline"

create_node NX_V1 '{
  "project_id": "'$PROJECT_NEXT'",
  "node_type": "discovery",
  "title": "NextJS standalone build needs devDependencies at build time",
  "properties": {
    "description": "Using npm ci --omit=dev in the Docker build fails because @tailwindcss/postcss is a devDependency but is required during the NextJS production build step. The Tailwind PostCSS plugin processes CSS at build time, not runtime.",
    "category": "edge_case",
    "severity": "medium",
    "resolved": true,
    "resolution": "Changed Dockerfile to npm ci (install all deps including dev) since they are needed at build time. The multi-stage build ensures only the standalone output (~150MB) ends up in the production image."
  },
  "created_by": "danny"
}' "Discovery: devDeps needed at build"

# ==========================================================================
# STEP 7: Python Indexer — Decisions & Architecture
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 7: Python Indexer ━━━${NC}\n"

create_node PY_D1 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "decision",
  "title": "Use tree-sitter for multi-language code parsing",
  "properties": {
    "context": "The code indexer needs to parse TypeScript, Python, and Dart source files to extract functions, classes, components, and their relationships. We need a parser that handles all 3 languages consistently without writing custom parsers for each.",
    "rationale": "tree-sitter provides language-agnostic AST parsing with official grammar bindings for all 3 target languages. The py-tree-sitter binding gives direct control over grammar versions and performs better than alternatives. Each parser implements BaseParser.parse() returning a list of Symbol objects.",
    "alternatives": ["ast module (Python only) — language-specific", "Babel/TypeScript compiler API — JS-only", "Regular expressions — fragile and incomplete", "Language Server Protocol — heavyweight for batch processing"],
    "impact": "parsers/ directory has one parser per language (typescript.py, python_lang.py, dart.py). A registry in __init__.py maps file extensions to parser singletons. Parser singletons are lazy-cached.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: tree-sitter for parsing"

create_node PY_D2 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "decision",
  "title": "Haiku 4.5 for AI code summarization with hash caching",
  "properties": {
    "context": "Each extracted code symbol (function, class) needs a one-line description for the knowledge graph. We need AI summarization that is fast, cheap, and deterministic enough to skip unchanged symbols.",
    "rationale": "Claude Haiku 4.5 provides sufficient quality for one-line descriptions at ~10x lower cost than Sonnet. SHA-256 hash of the function body acts as a cache key — if the hash matches a previously summarized version, we skip the API call. Batch up to 50 symbols per request for efficiency.",
    "alternatives": ["Sonnet 4 — better quality but 10x cost", "Local model (Ollama) — no API cost but requires GPU", "Static analysis only — misses intent and context"],
    "impact": "summarizer/claude.py handles Anthropic SDK calls. summarizer/cache.py manages the hash-based cache. Works gracefully without ANTHROPIC_API_KEY — just skips summarization.",
    "status": "accepted"
  },
  "created_by": "danny",
  "scope": "architecture"
}' "Decision: Haiku 4.5 summarization"

create_node PY_D3 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "decision",
  "title": "uv as Python package manager for 10-100x faster installs",
  "properties": {
    "context": "Python package management with pip/poetry is slow, especially in Docker builds. The project uses PEP 621 standard pyproject.toml. We need fast, reliable dependency resolution.",
    "rationale": "uv provides 10-100x faster installs than pip/poetry. It supports standard pyproject.toml with hatchling build backend. uv sync --frozen ensures reproducible builds from uv.lock. Docker multi-stage builds copy only the .venv for minimal production images.",
    "alternatives": ["Poetry — slower but more mature", "pip + requirements.txt — manual lock management", "conda — not suited for web services"],
    "impact": "pyproject.toml uses hatchling build backend with src/ennam_kg layout. Dockerfile copies uv from ghcr.io/astral-sh/uv:latest. Install is ~2 seconds in Docker.",
    "status": "accepted"
  },
  "created_by": "danny"
}' "Decision: uv package manager"

create_node PY_C1 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "concept",
  "title": "Indexing Pipeline",
  "properties": {
    "name": "Indexing Pipeline",
    "definition": "The 5-stage process that converts source code into knowledge graph nodes: (1) Scanner discovers files respecting .gitignore, (2) Parser extracts AST symbols via tree-sitter, (3) Extractor maps symbols to Go API node payloads, (4) Differ compares against existing KG nodes by natural key (file_path:name:kind + body_hash), (5) Engine orchestrates create/update/archive operations via KGClient.",
    "domain": "code-indexing",
    "aliases": ["indexing flow", "code scan pipeline"]
  },
  "created_by": "danny"
}' "Concept: Indexing Pipeline"

create_node PY_C2 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "concept",
  "title": "Symbol",
  "properties": {
    "name": "Symbol",
    "definition": "A code element extracted by tree-sitter parsing. Has attributes: name, kind (SymbolKind enum: FUNCTION, CLASS, COMPONENT, etc.), file_path, line_start, line_end, signature, body_hash (SHA-256 of body text). Symbols are the intermediate representation between raw source code and KG nodes.",
    "domain": "code-indexing",
    "aliases": ["code symbol", "AST symbol", "extracted element"]
  },
  "created_by": "danny"
}' "Concept: Symbol"

create_node PY_A1 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "architecture",
  "title": "Python Service Entry Points",
  "properties": {
    "arch_type": "pattern",
    "content": "## Two Entry Points\n\n### FastAPI HTTP Server (main.py)\n- POST /index — Trigger full repository scan\n- POST /index/incremental — Scan only changed files\n- GET /healthz — Health check\n- Lifespan manages shared httpx.AsyncClient\n\n### Queue Worker (worker.py)\n- Standalone process: python -m ennam_kg.worker\n- Redis BRPOP loop consuming indexing jobs\n- Consumes index_project and index_changed messages\n- Signal handlers (SIGINT/SIGTERM) for graceful shutdown\n\n## Shared Pipeline\nBoth entry points use the same indexing engine:\nscanner → parser → extractor → differ → KGClient",
    "content_format": "markdown"
  },
  "created_by": "danny"
}' "Architecture: Python entry points"

create_node PY_T1 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "task",
  "title": "Implement TypeScript tree-sitter parser",
  "properties": {
    "task_id": "TASK-020",
    "description": "Create parsers/typescript.py that extracts functions, classes, React components (arrow functions with JSX return), exports, and route definitions from TypeScript/TSX files using tree-sitter-typescript grammar.",
    "status": "completed",
    "assignee": "claude-code"
  },
  "created_by": "danny"
}' "Task: TypeScript parser"

create_node PY_T2 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "task",
  "title": "Build indexing differ for create/update/archive",
  "properties": {
    "task_id": "TASK-021",
    "description": "Implement indexer/differ.py that compares newly extracted symbols against existing KG nodes. Uses natural key (file_path:name:kind) for matching and body_hash for change detection. Produces three lists: nodes to create, nodes to update, nodes to archive (removed from source).",
    "status": "completed",
    "assignee": "claude-code"
  },
  "created_by": "danny"
}' "Task: Indexing differ"

create_node PY_V1 '{
  "project_id": "'$PROJECT_PYTHON'",
  "node_type": "discovery",
  "title": "Python src layout needs PYTHONPATH in Docker",
  "properties": {
    "description": "The project uses PEP 621 src layout (src/ennam_kg/). Running uv sync --frozen --no-dev installs dependencies but does not install the project package itself when the source is not present during dependency resolution. Python cannot find the ennam_kg module at runtime.",
    "category": "edge_case",
    "severity": "high",
    "resolved": true,
    "resolution": "Two fixes: (1) COPY src/ before uv sync so the project package is installed alongside deps, (2) Add ENV PYTHONPATH=/app/src as fallback. Both ensure the module is importable."
  },
  "created_by": "danny"
}' "Discovery: PYTHONPATH in Docker"

# ==========================================================================
# STEP 8: Cross-platform edges
# ==========================================================================
echo ""
printf "${YELLOW}━━━ Step 8: Edges (relationships) ━━━${NC}\n"

# Go internal edges
create_edge "$PROJECT_GO" "$GO_D1" "$GO_C1" "relates_to" "PostgreSQL decision → Knowledge Node concept"
create_edge "$PROJECT_GO" "$GO_D2" "$GO_C2" "relates_to" "Gate validation decision → Edge Whitelist concept"
create_edge "$PROJECT_GO" "$GO_D2" "$GO_C3" "relates_to" "Gate validation decision → Completeness Scope"
create_edge "$PROJECT_GO" "$GO_D5" "$GO_A3" "impacts" "Layered arch decision → Composition Root"
create_edge "$PROJECT_GO" "$GO_D1" "$GO_A2" "impacts" "PostgreSQL decision → DB Schema"
create_edge "$PROJECT_GO" "$GO_D3" "$GO_A1" "impacts" "Redis queue decision → API Catalog"
create_edge "$PROJECT_GO" "$GO_R1" "$GO_C4" "relates_to" "API key auth requirement → Developer Identity"
create_edge "$PROJECT_GO" "$GO_T1" "$GO_R2" "implements" "Graph traversal task → Node CRUD requirement"
create_edge "$PROJECT_GO" "$GO_V1" "$GO_D1" "about" "migrate.Close() bug → PostgreSQL decision"
create_edge "$PROJECT_GO" "$GO_V2" "$GO_A3" "about" "Air version discovery → Composition Root"

# NextJS internal edges
create_edge "$PROJECT_NEXT" "$NX_D1" "$NX_C1" "relates_to" "BFF decision → BFF Proxy concept"
create_edge "$PROJECT_NEXT" "$NX_D3" "$NX_C2" "relates_to" "TanStack Query decision → Project Context"
create_edge "$PROJECT_NEXT" "$NX_D2" "$NX_A1" "impacts" "Cytoscape decision → Dashboard pages"
create_edge "$PROJECT_NEXT" "$NX_T1" "$NX_D2" "relates_to" "Graph viz task → Cytoscape decision"
create_edge "$PROJECT_NEXT" "$NX_V1" "$NX_A1" "about" "devDeps discovery → Dashboard architecture"

# Python internal edges
create_edge "$PROJECT_PYTHON" "$PY_D1" "$PY_C2" "relates_to" "tree-sitter decision → Symbol concept"
create_edge "$PROJECT_PYTHON" "$PY_D2" "$PY_C1" "relates_to" "Haiku decision → Indexing Pipeline"
create_edge "$PROJECT_PYTHON" "$PY_T1" "$PY_C2" "relates_to" "TypeScript parser task → Symbol concept"
create_edge "$PROJECT_PYTHON" "$PY_V1" "$PY_A1" "about" "PYTHONPATH discovery → Python entry points"

# ==========================================================================
# Summary
# ==========================================================================
echo ""
printf "${CYAN}══════════════════════════════════════════════════════════════${NC}\n"
printf "${CYAN}  Seed Complete${NC}\n"
printf "${CYAN}══════════════════════════════════════════════════════════════${NC}\n"
echo ""
printf "  Nodes created:  ${GREEN}$CREATED${NC}"
[[ $FAILED -gt 0 ]] && printf "  (${RED}$FAILED failed${NC})"
echo ""
printf "  Edges created:  ${GREEN}$EDGE_CREATED${NC}"
[[ $EDGE_FAILED -gt 0 ]] && printf "  (${RED}$EDGE_FAILED failed${NC})"
echo ""
echo ""
printf "  Projects:\n"
printf "    Go API:     ${CYAN}$PROJECT_GO${NC}\n"
printf "    NextJS:     ${CYAN}$PROJECT_NEXT${NC}\n"
printf "    Python:     ${CYAN}$PROJECT_PYTHON${NC}\n"
echo ""
printf "  API Key:      ennam_kg_danny_test_b13b555c5533e45df5d613d8ab94500f\n"
printf "  Dashboard:    http://localhost:3001\n"
echo ""
