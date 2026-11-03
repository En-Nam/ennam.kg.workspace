# Checkpoint: claude — 2026-11-03 (DAAB authz hardening + user/project UX)

## What was done
- Dashboard proxy never uses KG_API_KEY for anonymous callers; only GET settings/public passes (Go exempts it). Dead src/lib/api removed.
- Supabase login no longer JIT-creates users (existing DAAB user or KG_SUPABASE_ADMIN_EMAILS only; else 403 "account not provisioned").
- adminOnly guard on queue/*, usage/dashboard, rate-limit/status, POST ai/request.
- GET /projects/{id} and /stats use requireProjectVisible: non-admin members were getting 403 on Overview/Members/Sources (pre-existing bug: web session keys have no project_ids).
- Password change now ends the session (it was an infinite forced-change loop on the Supabase path).
- Create User: Viewer default and project picker; no-projects notice for non-admins; "developer" shown as "Editor" in the UI only (stored value unchanged).

## Commits
- ennam.kg.go: 30ee18f, 722f44a, bbfdd3d, a2b1ea2
- ennam.kg.next: 980a8b2, 66d4e2d, 2901554, 030a061
- Pushed to task/DAAB/improve, merged to main and deploy-* (see the session's final message).

## Verification
- go test -race passes. Next build OK.
- Live checks against the local stack with real user-linked keys:
  - authz matrix
  - UI checks (Playwright)
  - real Supabase create → temp-password login → forced change → re-login
  - stranger rejected
  - 15-page sweep as Editor and Viewer: zero failed requests
- Test accounts deleted in DAAB and Supabase. The local DB has 0 nodes, so data-dependent views were not exercised.

## Next steps / open
- User to-do:
  - Deploy kg-server before the dashboard.
  - Confirm KG_SUPABASE_SERVICE_ROLE_KEY is set on ECS.
  - Disable Supabase public signup.
  - Run the stranger-users and api_keys audit SQL on the deployed DB.
  - Rotate "Admin Key 2": the replacement must be admin with project_ids [] and no user. Keep KG_API_KEY in the root .env (release compose requires it).
- Same empty-project_ids bug remains in history, document-meta, document-structure, outline, backlinks, section-neighbors, ingest-status, retrieve/graph and graphrag/link. No dashboard caller found; not fixed.
- A project-level admin (not global) gets no user list in Add Member (/users is global-admin only). Needs a product decision.
- Adding a member with a user-less API key returns 500 (added_by gets the name, not a UUID). Pre-existing, not fixed.
- Org model in DAAB: deferred. Every design doc reviewed points to customers using DAAB only through LAAM; the root specs (C:\Projects\ennam\docs) were not reviewable here. Awaiting the user's confirmation. If needed later, Ennam Admin should own orgs, and this conflicts with 1G shared projects.
