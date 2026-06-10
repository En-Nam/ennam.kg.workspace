# Backlog (Go API) — path-level project-access not enforced on `/projects/{id}/...`

**Surfaced**: 2026-06-10, during IMP-005 code review.
**Severity**: MEDIUM (latent authorization gap; not introduced by IMP-005).

## What
The `ProjectID` middleware (`internal/middleware/project.go`) enforces a caller's
project access ONLY for the project resolved from the **header/query** param. For
endpoints that carry the project in the **path** — `/api/v1/projects/{id}/...` — it
resolves nothing and passes through (see its line ~107: "No project ID resolved —
pass through"). The handlers for these path endpoints (e.g. `document.go`
ListNodeEmbeddings / BatchUpsertEmbeddings, `kg_generation.go`, `draft_node.go`)
do NOT add a per-request check that the authenticated key/user belongs to `{id}`.

Net effect: a valid API key could read/write another project's data via the path id,
unless the deployment scopes keys narrowly. Today this is mitigated because these are
internal endpoints driven by the internal key.

## Why it matters
`project_members` is the authoritative access source (per Go CLAUDE.md), but path
endpoints bypass it. If any `/projects/{id}/...` endpoint is ever exposed to
multi-tenant/untrusted callers, this is a cross-project data exposure.

## Fix options (not started)
1. Extend `ProjectID` middleware to also read `r.PathValue("id")`/`{projectId}` and
   run the same access check.
2. Or a small handler helper `requireProjectAccess(ctx, projectID)` used by each
   path endpoint.
Either is codebase-wide (touches several handlers) → deliberately deferred, not a
fork onto IMP-005's two endpoints only. IMP-005's `ListNodeEmbeddings` documents the
current trust model inline as an interim measure.
