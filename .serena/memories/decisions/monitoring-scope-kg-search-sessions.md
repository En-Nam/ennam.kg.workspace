# Decision — Cross-User `monitoring` Scope for `kg_search_sessions`

**Status:** DECIDED · **Date:** 2026-06-29 · **Author:** DAAB session
**Unlocks:** LAAM Phase-2 (`kg_search_sessions` consume-shared)
**Related:** `mem:backlog/daab-kg-search-sessions-followups` · `mem:decisions/ecosystem-hermes-allocation`

---

## Context

`kg_search_sessions` (shipped 2026-06-29, branch `task/implement_docs_sync`) scopes all results to the authenticated user's own sessions. LAAM Phase-2 needs to search across **all users' sessions within a project** so it can monitor agent transcripts. This requires a privileged `monitoring` scope.

The current tool was designed opaque (scope unwidenable by body/header — security-reviewed). This decision specifies how to safely widen scope via an explicit, server-enforced parameter.

---

## Decision

### API change
Add `scope` parameter to `kg_search_sessions`:

```
scope: "user" | "monitoring"   // default: "user"
```

- **`"user"` (default):** existing behavior — results scoped to the calling principal's `user_id`. No change for any existing caller.
- **`"monitoring"`:** results scoped to all users within the calling principal's `project_id`. Cross-user, never cross-project.

### Authorization gate
- `"monitoring"` scope is ONLY permitted when the API key's principal holds `project_role = 'admin'` for the project.
- Reuse existing RBAC (`project_members.role`). Do NOT invent a new role.
- If a non-admin principal passes `scope=monitoring`, the server MUST reject with `403` (not silently downgrade to user scope — silent downgrade hides misconfiguration).

### Project boundary — invariant maintained
`project_id` is always derived from the API key's project binding. The `monitoring` scope widens across users within that project only. Cross-project search remains impossible regardless of scope value. This is the same invariant enforced in v1 (body/header cannot override project).

### Audit log
Every `monitoring`-scope query MUST be written to an audit log before results are returned:

```
{timestamp, project_id, principal_id, scope, query, result_count}
```

Do NOT log returned content (only metadata). Suggested table: `kg_audit_log` (new, append-only). If not yet built, write to `slog` structured log at WARN level with a `monitoring_scope_query` key as an interim — but add the table before LAAM goes live.

### LAAM integration pattern
LAAM uses a single project-level admin API key (set up once per project, not per-user). It passes `scope=monitoring` to search its project's monitored transcripts. Qwen 8B receives results read-only — write/curation stays off the 8B (existing constraint, unchanged).

---

## Threat Model

### T1 — Privilege escalation (normal user → monitoring scope)
- **Vector:** Non-admin caller passes `scope=monitoring`.
- **Impact:** Reads all users' session content within the project.
- **Mitigation:** Server-side `project_role = 'admin'` check before query executes. 403 on failure. Parameter is ignored at the SQL layer unless check passes (defense in depth).
- **Residual:** LOW. Server-enforced, not client-enforced.

### T2 — Cross-project leak
- **Vector:** Monitoring-scope query somehow reaches another project's sessions.
- **Impact:** Cross-project session content exposure.
- **Mitigation:** `project_id` derived from API key binding (existing invariant). SQL WHERE always includes `project_id = $bound_project`. No override path exists.
- **Residual:** NEGLIGIBLE. Invariant pre-dates this decision and was already security-reviewed.

### T3 — Stolen monitoring-role key → mass surveillance
- **Vector:** Attacker acquires an admin API key and calls `kg_search_sessions` with `scope=monitoring`.
- **Impact:** Full session history of all users in the project exposed.
- **Mitigation:** Key rotation policy (key compromise → rotate immediately, sessions already happened so content is static — audit log shows the breach). Rate limiting on the search endpoint. Audit log enables post-breach forensics.
- **Residual:** MEDIUM — inherent to any privileged long-lived credential. Accept with controls. Recommendation: monitoring keys should be short-lived / rotated on schedule; treat the audit log as a security artifact.

### T4 — Audit log poisoning via session content
- **Vector:** Malicious session content is stored then returned in a query; log consumer processes it unsafely.
- **Impact:** Log injection / reader exploitation.
- **Mitigation:** Audit log stores only metadata (query string, result_count, principal_id, timestamp). Returned content is NOT written to the audit log. Log consumer must treat all string fields as untrusted.
- **Residual:** LOW.

### T5 — Role assignment abuse (admin assigns monitoring role to malicious agent)
- **Vector:** A compromised project admin grants admin role to an attacker-controlled principal.
- **Impact:** Same as T3.
- **Mitigation:** Role assignment itself is admin-only and governed by existing RBAC. Out of scope for this decision. Accept: role assignment abuse is a broader governance problem, not specific to monitoring scope.
- **Residual:** LOW (accept — covered by existing controls).

---

## What is explicitly OUT OF SCOPE

- **Cross-project admin scope** — searching across projects. Not decided here; requires a separate decision + much stronger isolation proof.
- **AAAA consuming monitoring scope** — AAAA has no session search use case and has a multi-tenancy hard blocker. Skip.
- **Retention / expiry policy for audit logs** — separate ops decision.
- **`response_blocks` indexing, trigram/CJK, hybrid RRF** — separate follow-ups per `mem:backlog/daab-kg-search-sessions-followups`.

---

## Implementation checklist (for when this is built)

- [ ] Add `scope` field to `kg_search_sessions` MCP tool schema (opaque to caller — server resolves)
- [ ] REST handler: read `scope`, check `project_role = 'admin'` if `monitoring`, else 403
- [ ] SQL: `monitoring` scope removes `AND tm.user_id = $user_id` predicate; project_id filter unchanged
- [ ] Create `kg_audit_log` table (or interim slog at WARN) — write before query executes
- [ ] Update MCP bridge: pass `scope` through; bridge must NOT allow client to bypass the 403
- [ ] Integration test: non-admin + `scope=monitoring` → 403; admin → results across users; project boundary still holds
- [ ] Security review before merging (this touches privilege boundary)
