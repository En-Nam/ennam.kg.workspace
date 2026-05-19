# QA NextJS Bug Fixes — 2026-04-16

**Status**: ALL NextJS bugs from QA report FIXED
**Commits**: `fdf3025`, `6ee0a73` on main (pushed)

## Fixed Bugs

| # | Priority | Bug | Fix | Commit |
|---|----------|-----|-----|--------|
| 6 | P1 | Create Project CTA → dead `/projects/new` route | Replaced with inline `CreateProjectDialog` (same pattern as DataSourceForm) | fdf3025 |
| 7 | P1 | Edit Project CTA → empty onClick | Added `EditProjectDialog` pre-filled with current data, uses `useUpdateProject()` | fdf3025 |
| — | P2 | Stat cards show "undefined" on `/projects/[id]` | Guarded with `?? 0`: `String(stats.node_count ?? 0)` | 6ee0a73 |
| — | P2 | Admin Sync "Trigger Sync" disabled no tooltip | Added `title="Select a data source first"` | 6ee0a73 |
| — | P2 | Admin Sync "Export CSV" disabled no tooltip | Added `title="No sync history to export"` | 6ee0a73 |
| — | P2 | Chat Demo disabled tools no tooltip | Added `disabledReason` field to all 9 tools in ToolMenu | 6ee0a73 |
| — | P3 | Query send icon no aria-label | Added `aria-label="Send query"` | 6ee0a73 |
| — | P2 | `/settings/users` "Coming Soon" placeholder | Replaced with redirect message + link to `/admin/users` | 6ee0a73 |

## New Files Created
- `src/components/projects/CreateProjectDialog.tsx` — Create project dialog with name/description/repo_url
- `src/components/projects/EditProjectDialog.tsx` — Edit project dialog pre-filled with current data

## QA Report Status (NextJS items)
- P1 #6 Create Project CTA: **FIXED**
- P1 #7 Edit Project CTA: **FIXED**
- P2 Dead CTAs: **ALL FIXED** (tooltips added)
- P2 Ghost buttons: **FIXED** (disabledReason in ToolMenu)
- P2 Stat cards undefined: **FIXED**
- P3 Disabled tooltips: **FIXED**
- `/settings/users` placeholder: **FIXED** (redirects to /admin/users)

All NextJS items from QA functional-test-2026-04-16 are resolved.
