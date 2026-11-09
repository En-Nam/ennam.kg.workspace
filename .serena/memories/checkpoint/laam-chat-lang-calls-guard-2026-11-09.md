# Checkpoint: laam chat-lang-calls-guard — 2026-11-09 (LAAM repo, branch task/LAAM/improve)
(Written to the workspace Serena store: no activate_project tool in this session, so the LAAM store was unreachable.)

## What was done (LAAM commits 448cb09b..f73f5638, local only)
- Reply language: LANG_HINT pinned reply to UI locale; locale defaults "en" (082c35f8). Now: code detects message language
  (lib/chat/message-language.ts, conservative) and the system prompt NAMES it; generic rule + conversation + locale fallback
  otherwise. Closing turns (restateQuestion / synthNudge opt-in) pin the question's language. Generic rule alone: Sonnet 5-7/8
  wrong; named: 8/8.
- Small talk: 3 calls -> 1 (Claude): G4 off for Claude, no-tool draft reused (Claude only).
- Write-claim guard: clause-aware (negation scoped by punctuation+conjunctions, modal perfect, question scan punctuation-only).
- Container laam-app:latest rebuilt from HEAD content. Temp conversations deleted, usage_outbox kept.

## Open
- Bug 3 original blocked text unrecoverable; live q5 now takes "no open findings" path (DAAB has none) -> fix covered by unit tests only.
- owner.demo profile Tone "…, in English": named message language now wins over it (4/4 VI). Product decision for lead.
- Overrides b1e48507 (switch decides reply language). TTS voice still follows locale (voice mismatch possible).
- "vừa xong" timestamp shows in EN UI (i18n leftover, not this task).
- BytePlus/Cerebras: unchanged (G4 + closing stream kept), unmeasured.
