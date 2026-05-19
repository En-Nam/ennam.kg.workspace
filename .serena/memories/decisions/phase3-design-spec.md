# Phase 3 Design Spec — Projects, Users & Platform Administration

**Date**: 2026-04-13
**Status**: BA analysis COMPLETE — 3 formal BA documents produced, reviewed, and committed
**Design Spec**: `ennam.kg.requirements/documents/phase3/projects-users-platform-admin-spec.md`
**BA Documents**: `ennam.kg.requirements/documents/phase3/BA-014`, `BA-015`, `BA-016`

## Scope (7 modules)

| Module | Priority | New Endpoints | Key Decisions |
|--------|----------|---------------|---------------|
| M1: User Accounts | P0 | 8 | Username+password, admin-only creation, auto-generate internal API key per user |
| M2: Auth Login | P0 | 3 | Go API login endpoint, bcrypt, BFF stores key in iron-session |
| M3: Project CRUD | P0 | 5 | Create/update/archive, stats endpoint, membership-filtered list |
| M4: Project Members | P0 | 4 | Per-project roles (admin/developer/viewer), auto-sync API key project_ids |
| M5: API Key Management | P1 | 6 | Expose existing store via REST, internal keys hidden from list |
| M6: Activity Feed | P1 | 2 | Dashboard feed from existing audit_trail, add Phase 2 operations |
| M7: System Settings | P2 | 4 | Runtime DB-backed config overriding YAML defaults |

**Total**: 32 new endpoints, 2 modified, 4 new migrations (032-035), 37 business rules

## Key Architecture Decisions
- API key-based auth model preserved — users get auto-generated internal key
- `project_members` table = authoritative source (replaces `api_keys.project_ids` for user access)
- Per-project roles via project_members table (admin/developer/viewer)
- Login on Go API (source of truth), FE BFF proxy stores session in iron-session cookie
- Session: 15-day hard timeout, no auto-extend
- Account lockout: 5 failed attempts → locked, admin must unlock
- Password: bcrypt cost 12, min 8 chars + uppercase + number + special char
- Existing API keys → "system" users auto-created in migration 032
- ProjectID middleware needs to be wired in buildRouter()
- Settings override YAML at runtime — no restart needed

## BA Documents Produced
| BA | Title | FRs | NFRs | Endpoints | Migration |
|----|-------|-----|------|-----------|-----------|
| BA-014 | User Accounts & Auth | 6 | NFR-100→106 | 12 Go + 4 BFF | 032 |
| BA-015 | Project Management & Access | 6 | NFR-110→115 | 11 | 033 |
| BA-016 | Platform Administration | 5 | NFR-120→125 | 12 | 034, 035 |

## Development Order
BA-014 → BA-015 → BA-016 (sequential, auth dependency chain)
Python workers: NO CHANGES needed
