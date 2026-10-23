# Checkpoint: claude (LAAM harness hardening) — 2026-10-22

## What was done
Branch `feat/harness-hardening` in LAAM (8 commits, NOT pushed, NOT merged), items 1–5 of the harness weakness list (doc: claude.ai artifact "LAAM — Agent Harness Overview"):
1. test/helpers/packs.ts: PACKS_DIR → ../packs → ../ennam.kg.packs. The "7 red intel/admin tests" were env (no PACKS_DIR), not code; npm test now green with no env; 28 pack-content tests un-skipped.
2. scripts/eval/scenarios/mcp.ts: 9 MCP scenarios (neutral slug datahub, real `{text:"<json>"}` shape, serverNotes now passed by runner). Live k=2 gpt-oss-120b: sel 100%, args 100%, grounding 86%, termination 93%.
3. src/lib/agent/mcp-result-shape.test.ts: readers must match plain vs MCP-wrapped; recursive source scan fails on unlisted readers (mutation-verified).
4. src/lib/log.ts: JSON-line logs (msg keeps "[scope]" prefix); chat route (32), MCP, TTS converted. DEPLOYMENT §6.3 updated.
5. write-claim-guard: assign verbs (giao/phân công/gán, assign, 分配/指派) in intent; claims only in assistant voice; "<verb> xong". Real replies (309): guarded 9→73, replaced 0.
- Code review (subagent): 0 critical/high; 2 medium fixed (delivery "đơn đã giao" FP; giao thức/nhận), lows fixed.

## Verified
npm test 6788 pass; tsc clean (excl .next); lint no new warnings.

## Next steps / risks
- User decides push/merge. More write-intent turns are buffered (no live streaming/heartbeat) — existing behaviour now applies to assign asks.
- Items 2 (provider fallback), 3 (LAAM-owned memory), 1 (multi-instance) await product decisions.
