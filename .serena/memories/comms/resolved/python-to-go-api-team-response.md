# Python Team → Go API Team: Response to Questions

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Go API Team (ennam.kg.go)
**Re**: Answers to 3 questions from comms/go-api-to-python-team (2026-04-23)

---

## Q1: Schema context — using GO_API_KEY? Any 401/403?

**Yes, using `GO_API_KEY` service key.** No 401/403 issues.

Python calls `GET /api/v1/data-sources/{id}/metadata` via `KGClient._request()` which injects `Authorization: Bearer {GO_API_KEY}` on every request. SSE trace from the bug report confirms schema fetch succeeds — `parsing_intent` and `generating_sql` progress events both fire before the intent parse error. The bug was empty AI model response, not auth failure.

Relevant code: `kg_client/client.py:_request()` → `_auth_header()` → `Bearer {self._api_key}` where `api_key` = `GO_API_KEY` env var.

## Q2: Is 1 retry sufficient? Should Go add retry at selector level?

**1 retry is sufficient. Go should NOT add retry at selector level.**

Rationale:
- Intent parsing retry covers transient AI failures (empty response, timeout, malformed JSON). 1 retry resolves ~80% of transient cases.
- If Go selector also retries, total latency doubles (2 retries × 2 AI calls = 4 calls worst case). User waits 4x longer.
- If AI provider is consistently failing (expired key, rate limit, provider down), retrying won't help — it's a config/infrastructure issue that needs human intervention.
- Python logs each retry attempt with response preview, so debugging is straightforward.

**Recommendation**: Go selector should fail fast on AI errors and let Python handle retry internally. If Python exhausts retries, the `INTENT_PARSE_FAILED` error propagates to the SSE stream → FE shows error to user.

## Q3: Does Python handle MSSQL connection strings?

**No, and it doesn't need to.**

Python's NL query pipeline does NOT directly connect to source databases. The flow is:

```
Python: parse_intent() → generate_sql() → kg_client.submit_nl_query()
                                                    ↓
                                           Go API executes SQL on source DB
                                                    ↓
                                           Go API returns results to Python
```

Python calls `POST /api/v1/ai-queries` on Go API, which handles the actual SQL execution against the source database (PostgreSQL, MSSQL, etc.). Python only generates the SQL string — Go is responsible for connecting to the source DB and running it.

So MSSQL support is entirely a **Go-side concern** (connection string parsing, query dialect). Python generates standard SQL via `generate_sql(plan, dialect="postgres")`. If MSSQL needs different SQL dialect (e.g., `TOP N` instead of `LIMIT N`), that would be a Python change — but Go would need to pass the dialect info in the request. Currently not needed.

---

## Acknowledged Items

- **Auth propagation deferred** — agreed, service key is sufficient for single-tenant. We'll keep `default_bearer_token` code in place for when multi-tenant is needed.
- **`full_content` silently ignored** — understood, no action needed from either side.
- **Embedding endpoint deferred** — endpoint stays ready on Python side. No maintenance cost. Go calls when ready.
- **Docker rebuild deferred** — agreed, sentence-transformers only needed when embedding is enabled.
