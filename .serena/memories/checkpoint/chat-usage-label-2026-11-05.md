# Checkpoint: chat-usage-label — 2026-11-05

## What was done
- LAAM chat header token/cost label made correct: each assistant chat_message now stores the WHOLE turn's usage (migration 0050), summed from exactly the events recordUsage writes to usage_outbox (TurnUsage attached to the chat + chat_summary meters; DAAB calls counted when they run).
- Ennam-token charge computed per event at record time with charge.ts (port of Admin priceUsage, BigInt x10 000, per-event ceil); internal org gets a provider USD estimate with cache rates (pricing.js costUSDWithCache).
- Contract (both repos, byte-identical, sha pin updated): optional cache_read_multiplier / cache_write_multiplier per pricing.models entry; Admin currentPricing emits them only when non-null. CONTRACT_VERSION stays 1.
- UI: ChatUsageBadge (compact localized label + popover breakdown, partial-history notice, mobile icon+number); local-only = free; older rows = bare count + "Chưa đủ".

## Commits
- Admin 4195f8d (task/DAAB/improve). LAAM 46f746f5, adc21763, 818e038f (task/LAAM/improve). Not pushed.

## Current state
- Invariant test src/app/api/chat/route.usage.int.test.ts: stored usage = outbox (tool rounds, summary, suspended write, confirmed write). All suites green.
- E2E (internal org, claude-haiku-5-5): 9 calls; message = outbox exactly (225466 in / 2368 out / 185896 read / 23237 write / 0 DAAB); USD 7585 micros recomputed independently.

## Next steps / open
- Regenerate/Delete/Edit remove answers but their outbox events stay: the label then shows less than was charged.
- Customer "tokens charged" path and DAAB counting proven by tests only (e2e org is internal; its tools were not an org-provisioned DAAB).
- Confirm-path failures (Ollama narration 502, exception) write a "none" event with no answer row.
- Pricing snapshot at turn start (entitlement cache <= 60 s) vs Admin pricing by occurred_at.

## Blockers / Risks
- None.
