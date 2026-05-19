# API Documentation Status

**Updated**: 2026-04-09

## Documents (all in ennam.kg.next/docs/)

| File | Purpose | Endpoints | Status |
|------|---------|-----------|--------|
| `api-reference.md` | **Complete API catalog** — every endpoint in the system | 87 (2 public + 3 system + 38 Phase 1 + 55 Phase 2) | Verified against Go source |
| `phase2-api-contract.md` | Phase 2 definitive contract + FE path corrections | 55 Phase 2 endpoints | Verified + gaps closed |
| `phase2-api-integration.md` | TypeScript types + API client functions + hooks | Phase 2 only | Reference for FE implementation |

## Key Facts for FE Team
- Backend is source of truth — FE adapts paths, not vice versa
- 12 path corrections documented in phase2-api-contract.md
- Response patterns: bare arrays (most lists), wrapped objects (questions, runs, queue), direct structs (single entities)
- Credentials (connection_string, api_key) NEVER in responses (json:"-")
- Costs in microdollars (÷ 1,000,000 for display)
- Empty arrays return [] not null
- JSONB fields (results, metadata_json) may be null
