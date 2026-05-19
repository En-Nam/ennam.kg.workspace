# QA Test Scope by Phase

**Created**: 2026-04-15
**Usage**: QA agent reads this to know WHAT to test per phase. For HOW, see `qa/strategy-and-framework`.

---

## Phase 1 — Platform Foundation (BA-001 → BA-006)

**BA docs**: `ennam.kg.requirements/documents/phase1/`
**Status**: Implemented, needs E2E test coverage

### BA-001: Platform Foundation (45 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Node CRUD | Create, read, update, deprecate nodes | E2E-API | POST/GET/PATCH /projects/{id}/nodes |
| Edge CRUD | Create, delete edges between nodes | E2E-API | POST/DELETE /projects/{id}/edges |
| Search | Full-text search via pg_trgm | E2E-Browser | Search bar → results → click node |
| Traversal | Graph neighbors query | E2E-API | GET /projects/{id}/nodes/{id}/neighbors |
| Auth | API key authentication | E2E-API | X-API-Key header, 401 without key |
| Sessions | Start/end work sessions | E2E-API | POST/PATCH /sessions |
| Validation | Gate 1 (schema) + Gate 2 (completeness) | E2E-API | POST with invalid data → 400 |

### BA-002: MCP Bridge (26 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| MCP Tools | 25 MCP tools execute correctly | E2E-API (via MCP client) |
| Auto-injection | Session context injected into tool calls | E2E-API |
| Error handling | Invalid tool params → structured error | E2E-API |

### BA-003: Code Indexing (33 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| Indexing trigger | POST index job → Redis queue → Python processes | E2E-API |
| AST parsing | Python/TypeScript/Go file → correct symbols | Integration |
| AI summary | Symbols get AI-generated descriptions | Integration |

### BA-004: Dashboard (48 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Graph viz | Cytoscape.js renders nodes/edges | E2E-Browser | /graph page → nodes visible |
| Search | Cmd+K search → results | E2E-Browser | Keyboard shortcut → type → click result |
| Navigation | 14 routes accessible | E2E-Browser | Sidebar links → correct pages |
| BFF proxy | API calls proxied correctly | E2E-Browser | Network tab shows /api/kg/ calls |

### BA-005: Enforcement (24 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| Gate 1 | Schema validation on create/update | E2E-API |
| Gate 2 | Knowledge completeness checks | E2E-API |
| Edge whitelist | Only allowed edge types accepted | E2E-API |

### BA-006: Deployment (38 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| Docker | All 6 services start healthy | E2E-Infra |
| Health checks | /health endpoints return 200 | E2E-API |
| Migrations | All migrations apply without error | E2E-Infra |

---

## Phase 2 — Knowledge Graph AI Pipeline (BA-007 → BA-013)

**BA docs**: `ennam.kg.requirements/documents/phase2/`
**Status**: Implemented (Go + Python), Frontend partial

### BA-007: Data Source Connection (36 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Registration | Register PostgreSQL data source | E2E-Browser | Settings → Add Data Source → fill form → save |
| Connection test | Test connectivity + SSL | E2E-Browser | Click "Test Connection" → success/fail indicator |
| Schema extraction | Extract tables/columns/FKs | E2E-Browser | Click "Extract Schema" → progress → table list |
| Incremental sync | Re-sync detects changes | E2E-API | POST sync → diff report |

### BA-008: KG Generation (30 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| Explicit mapping | FK → graph edges | E2E-API |
| Implicit detection | AI detects non-FK relationships | E2E-API |
| Confidence scoring | Explicit=1.0, AI-detected=0.0-1.0 | E2E-API |

### BA-009: AI Provider (29 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| Provider registry | CRUD AI providers | E2E-API |
| Circuit breaker | 3 failures → circuit open | E2E-API |
| Failover | Primary → fallback on error | E2E-API |
| Budget tracking | Token usage logged correctly | E2E-API |

### BA-010: KG Visualization (42 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Graph rendering | Schema graph renders with nodes/edges | E2E-Browser | /schema-graph → Cytoscape canvas |
| Interactions | Zoom, pan, hover tooltips, click node | E2E-Browser | Mouse interactions on canvas |
| Edge styling | FK=solid, AI=dashed, confidence opacity | E2E-Browser | Visual inspection + screenshot |
| Layouts | Force-directed, hierarchical, radial, grouped | E2E-Browser | Layout dropdown → graph re-arranges |
| Export | PNG/SVG download | E2E-Browser | Click export → file downloads |

### BA-011: AI NL Query (40 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Query input | Type NL query → submit | E2E-Browser | Query page → type → Enter |
| SQL generation | AI generates correct SQL | E2E-API | POST /ai-query → check generated_sql |
| Result display | Table renders with correct data | E2E-Browser | Results table visible after query |
| Query history | Past queries listed | E2E-Browser | History sidebar → click to re-run |
| Error handling | Ambiguous query → clarification | E2E-Browser | AI asks follow-up question |

### BA-012: Admin Sync Portal (38 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| Sync trigger | Admin triggers sync | E2E-Browser |
| Progress | WebSocket/SSE shows progress | E2E-Browser |
| Queue | FIFO queue management | E2E-API |
| Rate limiting | Concurrent user limits enforced | E2E-API |

### BA-013: Benchmark Suite (30 ACs)
| Area | Test Focus | Type |
|------|-----------|------|
| Question bank | CRUD test questions | E2E-API |
| Test runner | Execute benchmark run | E2E-API |
| Accuracy scoring | Exact/semantic/partial/failure scoring | E2E-API |
| Regression | Compare current vs baseline | E2E-API |

---

## Phase 3 — Users & Projects (BA-014 → BA-016)

**BA docs**: `ennam.kg.requirements/documents/phase3/`
**Status**: Implemented

### BA-014: User Accounts & Auth (33 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Login | Username + password → dashboard | E2E-Browser | /login → fill → submit → redirect |
| Wrong password | Invalid credentials → error message | E2E-Browser | Fill wrong password → error shown |
| Account lockout | 5 failed attempts → locked | E2E-Browser | Login 5x wrong → "Account locked" |
| Admin unlock | Admin unlocks locked user | E2E-Browser | Admin → Users → Unlock button |
| Create user | Admin creates new user | E2E-Browser | Admin → Users → Create → fill form |
| Change password | User changes own password | E2E-Browser | Profile → Change Password |
| First login | pending_password_change → redirect | E2E-Browser | Login → forced to change-password page |
| Session expiry | 15-day timeout, no auto-extend | E2E-Browser | Verify session cookie maxAge |
| Disable user | Admin disables → user can't login | E2E-Browser | Admin disables → user login fails |

### BA-015: Project Management (30 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Create project | Admin creates → becomes admin | E2E-Browser | Projects → Create → fill → save |
| List projects | User sees only member projects | E2E-Browser | Login as developer1 → see assigned projects only |
| Add member | Project admin adds member | E2E-Browser | Project → Members → Add |
| Role permissions | Viewer can't create nodes | E2E-Browser | Login as viewer → Create button disabled/hidden |
| Archive | Admin archives → writes blocked | E2E-Browser | Archive → try create node → 403 |

### BA-016: Platform Administration (25 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| API keys | Create, list, revoke keys | E2E-Browser | Settings → API Keys → Create |
| Activity feed | Recent activity displayed | E2E-Browser | Dashboard home → activity widget |
| System settings | Admin changes setting → takes effect | E2E-Browser | Settings → change value → verify |
| Feature flags | Toggle feature → UI changes | E2E-Browser | Disable feature → page hidden |

---

## Phase 4 — AI Query UX (BA-017 → BA-019)

**BA docs**: `ennam.kg.requirements/documents/phase4/`
**Status**: Implemented

### BA-017: Conversational AI (35 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Create thread | New conversation thread | E2E-Browser | AI Query → New Thread → name it |
| Send query | Type NL query in thread | E2E-Browser | Thread → type → send → response streams |
| Streaming | Tokens appear progressively | E2E-Browser | Observe typewriter effect + progress stages |
| First token latency | < 3 seconds | Performance | Measure time to first visible token |
| Thread history | Prior messages in sidebar | E2E-Browser | Sidebar shows threads → click → messages load |
| Multi-turn | AI references prior context | E2E-Browser | Ask follow-up → AI uses prior query context |

### BA-018: Rich Response (36 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Chart rendering | Bar/line/pie charts render | E2E-Browser | Query aggregation → chart appears |
| Chart interactions | Hover tooltip, zoom, legend toggle | E2E-Browser | Hover data point → tooltip shows values |
| Markdown | Markdown formatted correctly | E2E-Browser | Explain query → markdown renders |
| Code blocks | SQL highlighted with copy button | E2E-Browser | Code block → syntax colors → copy works |
| Mixed response | Multiple blocks in one response | E2E-Browser | Response has markdown + chart + table |
| Smart aggregation | Large result auto-aggregated | E2E-Browser | Query 10K rows → chart shows aggregated |

### BA-019: AI Tools & Insights (49 ACs)
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| Tool menu | 9 tools visible on response | E2E-Browser | Response → toolbar with 9 icons |
| Export CSV | Download CSV file | E2E-Browser | Click Export CSV → file downloads |
| Explain query | AI explains reasoning | E2E-Browser | Click Explain → markdown explanation |
| Show as chart | Toggle table ↔ chart | E2E-Browser | Click Chart → chart appears → click again → table |
| Refine query | Edit and re-submit query | E2E-Browser | Click Refine → edit text → submit |
| Save favorite | Save query to favorites | E2E-Browser | Click Save → appears in favorites |
| Sort/Filter | Client-side sort/filter | E2E-Browser | Click column header → sorted |
| Compare | Side-by-side with previous | E2E-Browser | Click Compare → two tables shown |
| Summarize | AI data summary | E2E-Browser | Click Summarize → markdown summary |
| Download PDF | PDF file downloads | E2E-Browser | Click PDF → file downloads |
| Quick actions | 3 AI-suggested buttons | E2E-Browser | Response → 3 buttons below → click one |
| Insights | Confidence-labeled insights | E2E-Browser | Response → insight cards with badges |
| Insight accuracy | 80%+ correct | Manual | Run 20 queries → evaluate insight correctness |

---

## Phase 5 — AI Intelligence (BA-020 → BA-021)

**BA docs**: `ennam.kg.requirements/documents/phase5/`

### BA-020: Smart Context (39 ACs) — IMPLEMENTED
| Area | Test Focus | Type |
|------|-----------|------|
| Embedding generation | POST generate-embeddings → job completes | E2E-API |
| Embedding coverage | GET coverage → 100% tables embedded | E2E-API |
| Tier routing | Precise/Balanced/Fast produce different latencies | E2E-API + Performance |
| SQL accuracy | Precise tier ≥90% on benchmark | E2E-API + BA-013 |
| Context debug | SSE context_debug events when enabled | E2E-API |

### BA-021: Claude OAuth (31 ACs) — TODO
| Area | Test Focus | Type | Critical Paths |
|------|-----------|------|----------------|
| OAuth connect | Admin clicks Connect → redirects to Claude | E2E-Browser | Settings → Connect Claude → OAuth page |
| OAuth callback | Authorization code → token stored | E2E-Browser | Authorize → redirect back → status green |
| Token refresh | Auto-refresh before expiry | E2E-API | Verify background refresh works |
| Disconnect | Revoke token → fallback to API key | E2E-Browser | Settings → Disconnect → confirm → status grey |
| Provider fallback | OAuth unavailable → API key used | E2E-API | Remove token → AI calls still work via API key |
| Embedding provider | Switch between claude/openai/local | E2E-Browser | Settings → change provider → embeddings still work |

---

## Cross-Phase Test Suites

### Smoke Test (run after every deployment)
1. Dashboard loads (http://localhost:3500)
2. Login works (admin/password)
3. Project list loads
4. Create a node → appears in list
5. Search returns results
6. AI query returns response (if Phase 2+ configured)

### Regression Test (run before release)
All P0 + P1 test cases across all implemented phases.

### Performance Test
| Metric | Target | Phase | How to Measure |
|--------|--------|-------|----------------|
| Page load | < 2s | All | Playwright: measure navigation complete |
| Search response | < 500ms | 1 | Network request timing |
| AI first token | < 3s | 4 | SSE first content event timestamp |
| Chart render | < 2s | 4 | DOM mutation observer on chart container |
| Graph viz 100 nodes | < 2s | 2 | Cytoscape render complete event |
