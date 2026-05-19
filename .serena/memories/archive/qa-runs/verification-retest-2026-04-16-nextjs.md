# QA Verification Retest — NextJS Fixes 2026-04-16

**Status**: ALL NextJS bugs FIXED and pushed

## Fixes Applied (3 commits)

| Commit | Bugs Fixed |
|--------|-----------|
| `fdf3025` | P1 #6 Create Project CTA (dialog), P1 #7 Edit Project CTA (dialog) |
| `6ee0a73` | P2 stat cards undefined, P2 dead CTAs (tooltips), P3 aria-label, P2 settings/users redirect |
| `a102bec` | P2 Chat Demo tooltip on disabled buttons (span wrapper for pointer-events) |

## Final Bug Status

| # | Priority | Bug | Status |
|---|----------|-----|--------|
| 6 | P1 | Create Project dead route | **FIXED** — inline CreateProjectDialog |
| 7 | P1 | Edit Project empty onClick | **FIXED** — EditProjectDialog pre-filled |
| — | P2 | Stat cards "undefined" | **FIXED** — `?? 0` guard |
| — | P2 | Admin Sync disabled no tooltip | **FIXED** — native title attrs |
| — | P2 | Chat Demo disabled tooltip | **FIXED** — span wrapper + aria-disabled |
| — | P2 | Settings/Users placeholder | **FIXED** — redirect to /admin/users |
| — | P3 | Query send no aria-label | **FIXED** |

## Remaining (NOT NextJS)
- P1: Add Project Member — Go API `resolveUserID()` returns DeveloperName not UserID → **Go team**
- P2: Node history route not registered → **Go team**
- New: Login may revoke API key → **Design decision needed**

## Key Technical Fix
Disabled `<button>` has `pointer-events: none` (browser default) which blocks hover events for tooltips. Fix: use `aria-disabled` instead of `disabled` attr + wrap in `<span>` as TooltipTrigger render element. The span receives hover, tooltip fires. Button click guarded manually: `onClick={() => enabled && onAction(id)}`.
