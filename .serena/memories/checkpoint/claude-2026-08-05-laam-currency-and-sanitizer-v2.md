# Checkpoint: claude — 2026-08-05 (LAAM: currency-for-speech + sanitizer v2)

## 1. Currency formatting for TTS (user-reported: "$1,000.12" reads badly in Larvis voice)
- `src/lib/chat/voice.ts` — new `currencyToSpoken()` + regex `USD_SIGIL`, called at the START of the shared `cleanProse()` (used by both `stripForSpeech` and `extractForSpeech`). Converts "$1,000.12" → "1,000.12 USD" (number first, unit after — TTS-friendly), preserves a leading minus sign ("-$685.42" → "-685.42 USD"). Scoped to `$` (USD) only — no other currency evidenced in this data.
- Deliberately does NOT touch table/chart panel data: `tableToDescriptor`/`chartToDescriptor` read cell text BEFORE `cleanProse` runs, so the visual panel still shows "$1,000.12" as the model wrote it — only the spoken-prose channel is reformatted.
- 7 new tests in `voice.test.ts` (basic reformat, negative sign kept, no-decimal amount, multiple amounts in one sentence, and a dedicated `extractForSpeech` test proving the panel keeps "$" while speech outside the table gets reformatted).

## 2. Tool-call name sanitizer v2 (found during today's regression — NOT the same bug as the earlier `<|channel|>`/`[]` fix)
`src/lib/agent/orchestrator.ts`'s `sanitizeToolCallName` (from `mem:checkpoint/claude-2026-08-05-tool-name-sanitize`) only handled corruption with a special-char delimiter to cut at. Today's regression surfaced TWO more corruption shapes from gpt-oss-120b/BytePlus that slipped through:
- (b) alnum-only suffix glue, no delimiter to cut at: `kg_list_datasourcesjson` (valid tool `kg_list_datasources` + stray "json", maybe a leaked `response_format` token) — fixed by longest-matching-prefix search over `validNames`.
- (c) character substitution mid-string: `mcp__daab-michael-pharmacy_chain__kg_list_datasources` (real connector slug has "-", model produced "_") — fixed by normalizing "-"/"_" to the same char on both sides and comparing.
- Sanitizer now runs 3 steps in order (exact match → symbol-cut → longest-prefix → normalize-compare), stopping at the first hit; unmatched names still pass through unchanged (gate still fail-closed correctly for genuinely unknown tools).
- 3 new tests in `orchestrator.test.ts` (alnum-suffix-glue picks the right tool, longest-prefix wins over a shorter also-matching prefix, char-substitution normalize-match) using a small `mcpTools` fixture shaped like the real DAAB connector's tool names.
- `npx vitest run src/lib/agent src/app/api/chat src/lib/chat` → 444 passed. `npx tsc --noEmit` clean.

## Live verification via LAAM (dev server, hot-reload — `next dev`, no restart needed)
- Q9 ("cash drawer shortages") had failed in the previous round with exactly the `kg_list_datasourcesjson`/`pharmacy_chain` corruption in its tool-call trace. Retested: now correct — Robert Reed=9, cluster of 8s (Ethan Hill, Ava Wilson, Jessica Jackson, Daniel Ross), matching DB ground truth verified earlier in this thread.
- Currency fix not separately re-verified via a fresh Larvis run this session (the transform itself is unit-tested exhaustively; visually confirming in a live TTS session is a nice-to-have follow-up, not done here).

## Files changed
- `src/lib/chat/voice.ts`, `voice.test.ts`
- `src/lib/agent/orchestrator.ts`, `orchestrator.test.ts`

## Still open (not this fix's scope, flagged only)
- Q10 (insurance rejection rate) and Q2/Q5 occasional wrong-answer/give-up runs are DAAB-side NL2SQL plan-choice nondeterminism (see `mem:checkpoint/claude-2026-08-05-daab-*` series) or gpt-oss-120b reasoning nondeterminism — not a name-corruption issue, unaffected by this fix.
- Uncommitted, same as everything else in this thread.
