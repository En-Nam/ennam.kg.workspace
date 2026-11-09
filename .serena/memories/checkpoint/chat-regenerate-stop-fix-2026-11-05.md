# Checkpoint: chat-regenerate-stop-fix — 2026-11-05 (LAAM)

## What was done
- Regenerate now resends a question's raw images (ChatMsg.sent = {outgoing, images}, ephemeral). Unstored-question branch resends outgoing text (OCR blocks), images and attachment previews.
- Stop before first token: chat route stores a "stopped" answer (`src/lib/chat/stopped.ts`, trilingual) under assistantMsgId, both on tool-loop abort (was an API-error notice) and final-stream abort. Client shows the same text on AbortError (not for confirm round-trips).

## Files changed
- LAAM: src/app/api/chat/route.ts, route.test.ts, route.history-edit.int.test.ts; src/components/chat/ChatClient.tsx, ChatClient.test.tsx, types.ts; new src/lib/chat/stopped.ts

## Current state
- Unit chat route 173 pass, components+lib/chat 415 pass, tsc 0, eslint 0 errors; int history-edit 10 pass. Not committed (lead's instruction).

## Next steps / open
- Regenerate after reload has no images (not persisted). Options: base64 in attachments jsonb (no migration, heavy), new column/table (migration), object storage (no helper in LAAM).
- Ollama path ignores reqSignal: server stores the full answer while the client shows "(Đã dừng)".
- Stop before response headers then Regenerate stores a duplicate question (pre-existing).
- Stopped text lives outside i18n dictionaries; fold in later. CHANGELOG not updated.
