# Checkpoint: claude (LAAM memory auto-save + proactive alerts off) — 2026-10-22

## What was done
- 5e12bff9 feat(chat): proactive "Cảnh báo hệ thống" card opt-in via PROACTIVE_ALERTS=on (default off). Cause: abandoned Claude Code sessions never reach "done" → "agent kẹt 134481 phút" every 6h.
- 471495fc feat(memory): approval cards → auto-save after the answer + memory_saved notice with Undo (POST /api/memory/undo, sealed 24h token). /api/memory/confirm, MemoryProposalCard, clean-tools, confirm.ts, hasOutsideHistory removed. memory_* hidden from tool trace + citations.
- fc030763 fix(memory): memory_forget needs a forget cue or shared word in typed text (no restore in Settings; Undo line is ephemeral).
- Provenance (src/lib/memory/provenance.ts): note ≥70% fact words from typed text (titleHint; no attachment text), typed >600 chars refused, repeats vs DB notes in force refused.
- Tokens per model call 663 → 402 (o200k). Memory prep overlaps connector discovery. Stopped turn saves nothing.
- Spec §0 (v1.1) + CHANGELOG; decision `mem:decisions/memory-allocation-2026-10-22` updated.
- Verified on clean HEAD fc030763: tsc clean; unit+contracts 6877 pass (PACKS_DIR needed outside workspace); integration 579/579; db:generate no changes. Image rebuilt, laam-v2-app healthy on :3900.
- Live eval gpt-oss-120b k=3: 17/18; memory-save-only (live bug: DAAB call + PH-004 re-save) 3/3; ambiguous case saved "chuyển chỗ làm" 1/3 instead of asking.

## Next steps
- User to test on :3900; then push/merge task/LAAM/improve (unpushed).
- Phase 2 (separate switch): "nhớ các chat trước" via per-conversation summaries — only if user asks.
- Optional: "Khôi phục" button in Settings history.

## Blockers / Risks
- Security review flagged removal of the outside-input warning; accepted: replaced by code provenance + notice/Undo (attacker can only make it save words the user typed).
- Undo of a forget can be replayed if the user deletes the same note again in Settings within 24h (own note only).
- Another session commits workflow work on the same branch (954c757b).


## 2026-10-23 follow-up
- Live miss: "Mình là Dragoon, quản lý chi nhánh PH-004, cho xem doanh thu tuần này" → 9 data calls, no memory_save (tool WAS offered; snapshot taken). Eval could not reproduce (15/15 green even with intel note + ~50 tools, BytePlus and Cerebras).
- Fix 2c13fd73: memoryHint(userText) — vi/en/zh self-statement cue → one system line right before the user message ("call memory_save in your first tool round… if unclear, ask"). No cue = 0 tokens. "chuyển" deliberately NOT a cue (pushed memory-ask-when-ambiguous to save).
- cbf8f988: memory.int isolation test needed a typed forget request after fc030763 (was red since that commit).
- New eval memory-save-with-request (33 scenarios). Unit+contracts 6881 pass, integration 579/579, image rebuilt, :3900 healthy. Awaiting user re-test of step 1.