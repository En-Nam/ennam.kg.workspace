# Phase B: Deep Functional Tests — 2026-04-20

## Summary: 22 PASS, 3 FAIL, 2 SKIP

## Test Data Created
- 2 decision nodes, 1 concept, 1 architecture (all 201)
- 3 edges (decision->concept, decision->architecture, decision->decision) all 201
- 1 session (active)
- Discovery node failed (400 — field validation, needs debug)

## Functional Tests PASS
1. Search full-text "PostgreSQL" → total_count:2 ✅
2. Search filter by node_types ["decision"] → total_count:5 ✅
3. Neighbors query → total_count:3 (concept + architecture + decision) ✅
4. Traverse depth 2 → total_count:3 ✅
5. History → total_count:1 (initial version) ✅
6. Update node → version:2 ✅
7. History after update → total_count:2 (2 versions tracked) ✅
8. Session creation with session_id → status:active ✅

## Gate 1 Validation PASS
9. Short title (< 10 chars) → 400 ✅
10. Invalid enum (in-progress) → 400 ✅
11. Duplicate edge → 409 ✅
12. Non-whitelisted edge → 422 ✅

## Edges PASS
13. decision->concept (relates_to) → 201 ✅
14. decision->architecture (impacts) → 201 ✅
15. decision->decision (relates_to) → 201 ✅

## RBAC (from Phase A)
16-22. All viewer/developer RBAC tests PASS (verified in Phase A)

## FAIL
1. Discovery node creation → 400 (field validation — properties.category not recognized as top-level)
2. Deprecate node → empty response (may need different field names)
3. Data source registration → empty status (SSL require may fail against Docker PG without SSL)

## Key Insights
- Concept requires top-level: name, domain, definition (NOT in properties)
- Architecture requires top-level: arch_type, content (NOT in properties)
- Session requires session_id field
- Edge requires created_by field
- These field requirements differ from BA spec which puts them in properties{}
