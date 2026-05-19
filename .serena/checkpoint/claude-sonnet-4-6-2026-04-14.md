# Checkpoint: claude-sonnet-4-6 — 2026-04-14

## What was done
- Implemented Task 6: Format Detector (BA-018) using TDD
- Created `prompts.py` with `get_format_detection_prompt` and `get_insight_prompt`
- Created `format_detector.py` with `detect_format()`, `FormatResult`, `BlockSpec`
- Wrote 3 tests covering table format, chart+aggregation, and AI error fallback
- All 3 tests pass; ruff check and format clean

## Files changed
- Created: `src/ennam_kg/streaming/prompts.py`
- Created: `src/ennam_kg/streaming/format_detector.py`
- Created: `tests/test_streaming/test_format_detector.py`

## Current state
- Branch: `feature/phase4-sse-streaming`
- Commit: `be2abef` — all 3 tests passing, linted clean
- `get_insight_prompt` in prompts.py is ready for Task 8 (insight generation)

## Next steps
- Task 7 or Task 8: insight generation using `get_insight_prompt`
- Wire format detector into the streaming query engine

## Blockers / Risks
- None

---

# Checkpoint: claude-sonnet-4-6 — 2026-04-14 (Session 2)

## What was done
- Implemented Task 7: Block Composer + Engine Integration (BA-018)
- Created `block_composer.py` with `ResponseBlock` dataclass and `compose_blocks()` function
- Added `_infer_chart_type()` helper for chart type detection
- Modified `engine.py` to import and use `detect_format` + `compose_blocks`, emitting `format_metadata`, `block_start`, `block_content`, `block_end` SSE events after Stage 5
- Created `test_block_composer.py` with 3 tests (table, chart, empty results)
- Added `test_stream_emits_block_events` to `test_engine.py` using MultiCallAI (3 AI calls)
- Fixed lint issues: removed unused `field` import and unused `ResponseBlock` import in test

## Files changed
- `src/ennam_kg/streaming/block_composer.py` — new file
- `src/ennam_kg/streaming/engine.py` — Stage 5 replaced, block imports added
- `tests/test_streaming/test_block_composer.py` — new file
- `tests/test_streaming/test_engine.py` — new test added

## Current state
- 21/21 streaming tests pass (3 block_composer + 5 engine + 3 format_detector + 10 models)
- Lint clean, ruff format clean
- Committed on `feature/phase4-sse-streaming` — commit 4d6c57e

## Next steps
- Task 8 or beyond: BA-019 insights/suggested actions events

## Blockers / Risks
- None

---

# Checkpoint: claude-sonnet-4-6 — 2026-04-14 (Session 3)

## What was done
- Aligned Phase 4 frontend types with Go API contract (ennam.kg.next)
- Fixed 4 type files + 5 downstream consumer files, zero TS errors after all fixes

## Files changed
- `src/types/thread.ts` — `last_message_at: string | null`, `deleted_at`, 9 new ThreadMessage fields, ResultSummary/AggregationMetadata interfaces, SSE: stage_name→stage, stage_label→label, +index on ContentEvent, +retryable on ErrorEvent
- `src/types/insight.ts` — removed SuggestedAction interface
- `src/types/favorite.ts` — Favorite→ThreadFavorite, label required, result_snapshot/chart_config → Record, removed FavoriteList
- `src/hooks/use-favorites.ts` — updated to ThreadFavorite
- `src/components/chat/SuggestedActions.tsx` — updated to string[]
- `src/components/chat/ThreadSidebar.tsx` — fixed null guard on last_message_at
- `src/app/(dashboard)/favorites/page.tsx` — updated to ThreadFavorite
- `src/app/(dashboard)/chat-demo/page.tsx` — removed SuggestedAction, mocks use string[]

## Current state
- `npx tsc --noEmit` — 0 errors
- Committed on main — commit 972edec

## Next steps
- Wire new ThreadMessage fields (result_summary, aggregation_metadata, etc.) into chat UI components

## Blockers / Risks
- None
