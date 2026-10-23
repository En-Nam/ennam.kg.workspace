# Checkpoint: claude (LAAM personal memory, day 2) — 2026-10-23

## What was done
- Live miss fixed: intro + data request ("Mình là Dragoon, quản lý PH-004, cho xem doanh thu") answered with 9 data calls and no `memory_save` (tool was offered). `memoryHint(userText)` (src/lib/memory/prompt.ts): vi/en/zh self-statement cue → one system line right before the user message ("call memory_save in your first tool round… if unclear, ask"). No cue = 0 tokens. "chuyển" deliberately not a cue (it pushed memory-ask-when-ambiguous to save). Owner confirmed live: "Mình thích chơi game Cyberpunk" saved.
- Eval: new live-shaped `memory-save-with-request` (intel note + intel tools + ~50 DAAB filler tools; runner supports `extraSystem`, mirrors hint placement). 33 scenarios. Could NOT reproduce the live miss in eval (15/15 green, BytePlus + Cerebras) — the hint is a robustness fix, verified live only.
- memory.int isolation test fixed (red since fc030763: forget gate needed a typed forget request).
- Temporary chat: checkbox above composer → header switch next to "Cài đặt mô hình" (`TemporaryChatSwitch.tsx`), locked + visible on temporary conversations, hidden otherwise.
- Saved-memory notice: owner wanted it plain like ChatGPT → one muted line per change "🔖 Đã ghi nhớ: «…» · Hoàn tác · Quản lý bộ nhớ" (manage link only on the last line). A card version (d080f176) was rejected and reverted in a5c42e4e.

## Commits (LAAM `task/LAAM/improve`, NOT pushed)
2c13fd73 hint · cbf8f988 int test · dec05932 temp-chat switch · d080f176 card (superseded) · a5c42e4e quiet line

## Current state
- Unit+contracts 6881 pass, integration 579/579 (at cbf8f988); later UI commits: 474 related unit tests pass, tsc clean. Image rebuilt from clean worktree, :3900 healthy.
- UI changes not seen in a browser by the agent (needs owner login) — owner reviewing.

## Next steps
- Owner finishes the test guide (steps 2–19); then push/merge `task/LAAM/improve`.
- Optional: Loại 2 "nhớ các chat trước" (separate switch), "Khôi phục" in Settings history — only if asked.

## Blockers / Risks
- Hint relies on cue regex; a self-fact phrased without a cue may still be missed (model judgment). Provenance gate still blocks bad saves.
