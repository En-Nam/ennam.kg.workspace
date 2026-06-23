# Checkpoint: implementer — 2026-04-16

## What was done
- Fixed stat cards showing "undefined" on /projects/[id] by guarding with `?? 0`
- Added `title="Select a data source first"` to disabled Trigger Sync button on /admin/sync
- Added `title="No sync history to export"` to disabled Export CSV button in SyncHistory component
- Added disabled reason tooltips to all 9 tools in ToolMenu (chat-demo) — shows WHY disabled instead of just label+shortcut
- Added `aria-label="Send query"` to send button in QueryInput component (/query page)
- Replaced /settings/users "Coming Soon" stub with redirect link to /admin/users

## Files changed
- `ennam.kg.next/src/app/(dashboard)/projects/[id]/page.tsx` — stat cards ?? 0 guard
- `ennam.kg.next/src/app/(dashboard)/admin/sync/page.tsx` — title on disabled Trigger button
- `ennam.kg.next/src/components/admin/SyncHistory.tsx` — title on disabled Export CSV button
- `ennam.kg.next/src/components/chat/ToolMenu.tsx` — disabledReason field + conditional tooltip content
- `ennam.kg.next/src/components/query/QueryInput.tsx` — aria-label on send button
- `ennam.kg.next/src/app/(dashboard)/settings/users/page.tsx` — replaced stub with /admin/users redirect

## Current state
- TypeScript: 0 errors (tsc --noEmit clean)
- Committed to main: 6ee0a73

## Next steps
- QA can verify stat cards no longer show "undefined"
- QA can hover disabled buttons to confirm tooltip text appears
- /settings/users now shows a Go to Admin Users link

## Blockers / Risks
- None
