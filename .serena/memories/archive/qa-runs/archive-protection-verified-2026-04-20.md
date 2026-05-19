# Archive Write Protection — VERIFIED FIXED

**Date**: 2026-04-20
**Result**: ALL PASS

- Write node to archived project → 403 "cannot write to archived project"
- Write edge to archived project → 403 "cannot write to archived project"
- Read from archived project → 200 (allowed correctly)

Fix works at node/edge handler level, not just middleware. Both POST /nodes and POST /edges with archived project_id are blocked.

## All Phase A Bugs Now Resolved
- P0: API key auth ✅
- P0: Non-admin user creation ✅
- P0: Admin self-disable ✅
- P1: Same password ✅
- P1: Duplicate project 409 ✅
- P1: Thread filter + search ✅
- P1: Archive write protection ✅ (THIS FIX)
- P2: Login key revocation ✅
- RBAC: All 5 tests ✅
