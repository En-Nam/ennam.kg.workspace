# Checkpoint: laam reply-language-priority — 2026-11-09 (LAAM repo, branch task/LAAM/improve)
(Written to the workspace Serena store: no activate_project tool in this session, so the LAAM store was unreachable.)

## What was done (LAAM commits c4736cee..7e793e9f, local only, not pushed)
- One resolver lib/chat/reply-language.ts resolveReplyLanguage: request > profile > message > conversation > locale. The result is always named.
- Explicit requests detected in code (vi/en/zh patterns) and stored on chat_conversation.replyLanguage. Negatives: translation verbs, questions about a language, content tasks, quoted text.
- user_profile.replyLanguage (null = Auto), migration 0052. Settings → Profile select next to Tone, vi/en/zh.
- Chat main turn, confirm narration (replyLang sealed in the pending-write token), closing turns (restateQuestion/synthNudge write in and name replyLang), tail note "(Trả lời bằng tiếng Việt.)" placed AFTER the user message.
- Authoring chat: bubble uses replyLang, generated nodes use UI lang.
- Voice: reply_lang frame → constellation TTS lang.

## Measured
- Haiku "Dịch 'xin chào' sang tiếng Anh" in a vi thread: system hint alone gave 2–3/6 vi; rewording or writing the hint in vi gave 1–2/6; note before the message 5/6; note after it 6/6.
- Live on the container, 2× per model: a, b, c, d 4/4 each; e 2/2 on haiku (authoring model is org-configured, Sonnet not run); f cache_read > 0 on every request of turns 2–3.

## Current state
- owner.demo profile replyLanguage = en. Test conversations deleted, usage_outbox kept. Container rebuilt at 7e793e9f.

## Next / follow-ups
- Legacy user_profile.language column is dead (nothing reads or writes it from the UI): cleanup candidate.
- Browser-voice fallback and STT still use the UI locale.
- /api/workflows/generate: probe hardcodes lang "vi" and never passes lang to synthesizePlan (pre-existing).
