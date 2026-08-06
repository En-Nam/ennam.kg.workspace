# Checkpoint: claude — 2026-08-05 (DAAB fix #10: clarification options must explain meaning, not just name the column)

Follow-up to the demo-doc rewrite session. User pointed out `docs/demo-script-michael-pharmacy-12-questions.md` was written for an operator/demo-presenter (full of `transactions.total_amount`, `variance_quantity`, table names) when it should be for a normal end user who only knows plain business terms ("transaction ID", "amount"). Rewrote the doc for that single audience (see the doc itself — no longer dual-role). That rewrite surfaced a DEEPER, real system issue: some of DAAB's own clarification questions (from the metric-ambiguity mechanism, `mem:checkpoint/claude-2026-08-05-daab-metric-ambiguity-clarification`) leak raw table/column names as the PRIMARY content — e.g. Q8 asked "bạn muốn dùng bảng inventory_adjustments hay inventory_snapshots?" with column names (`product_id`, `quantity_before`) listed but nothing explaining what they MEAN. A non-technical user has no way to answer that.

User asked for my recommendation (advisory turn, no implementation) — recommended fixing the ROOT prompt rather than just the doc, flagged the tradeoff (my own earlier instruction told the AI to "put the actual column/aggregation in each option" for precision, which is what caused the jargon leak). User proposed a specific format ("Inventory Adjustments (inventory_adjustments)" — Title-Case the identifier, parenthetical reference). I pointed out that's cosmetic (de-snake-cases the name) but still doesn't explain MEANING, and proposed the stronger version: require a real plain-language explanation of what picking the option means, with the technical identifier only as a trailing reference. User chose the explanation-based version.

## Fix
`internal/service/query_intent.go` — replaced the narrow clarification-wording guidance inside the metric-ambiguity paragraph (previously: "put the actual column/aggregation in each option", with an example that was ITSELF just raw identifiers: `["Count of refund_items rows per product", "Sum of refund_items.quantity per product"]` — this was the direct cause of the jargon-leak bug) with a general rule that applies to ALL clarifications (not just metric-ambiguity — also missing-column and multiple-tables cases):
- States the target audience explicitly: "a NON-TECHNICAL person who has never seen this database schema — they know business words, not table or column names."
- Requires every option be a full explanatory sentence; the raw identifier may appear ONLY at the very end in parentheses, never as the option's main content and never as the ONLY content.
- Gives paired BAD/GOOD examples for both the metric-ambiguity shape (count vs sum) and the missing-info/multiple-tables shape (which table to use) — both in Vietnamese, matching the app's actual response language, so the AI has a concrete template to imitate rather than an abstract rule.
- `go build`, `go vet ./...`, `go test ./internal/service/...` all clean (pure prompt-text change, no logic touched — nothing new to unit-test deterministically for an LLM's own wording compliance).

## Deployment + verification
`docker restart daab-server`, healthy. Retested the exact question that exposed the original bug (Q8, "Which products have negative inventory?") **3x** via LAAM `/api/chat`:
- Run 1: still LEADS with the raw table name as a bullet header ("Dùng bảng `inventory_snapshots` – lấy số lượng hệ thống mới nhất...") but the explanatory content DOES follow — imperfect adherence (leads with jargon instead of trailing it) but not a bare unexplained list like before.
- Run 2: clean — describes each option in plain business terms ("Mỗi sản phẩm – lấy bản ghi snapshot mới nhất...", "Mỗi sản phẩm-cửa hàng...") with column names only as inline technical detail, not the lead.
- Run 3: answered directly (no clarification needed this round), correct answer, technical name only in parens as reference.

Also retested Q7 (voice) — its clarification came out well: "số lượng được hệ thống ghi lại (system_quantity) hay số lượng thực tế được kiểm kê (counted_quantity)" — a short but genuine explanatory qualifier attached to each raw name, readable by a lay user.

**Honest calibration**: this is a measurable improvement (from "bare identifier list, no explanation at all" to "explanation present in 2/3-3/3 runs, though not always leading/trailing in the exact position instructed") — not a 100%-compliant fix, since LLM instruction-following for stylistic/ordering details is inherently imperfect. No regressions observed in a quick sweep of Q1/Q7/Q9/Q10 (Q1's single hiccup was ordinary transient nondeterminism, unrelated).

## Files changed
- `ennam.kg.go/internal/service/query_intent.go`
- `docs/demo-script-michael-pharmacy-12-questions.md` (full rewrite this session, single end-user audience — see file for the 12-question plain-language guide)

## Cumulative DAAB fixes this whole multi-day thread: 10 total (all in `query_intent.go` + `sql_generator.go` + `ai_query.go`/`value_hints.go`), all verified via LAAM's real `/api/chat` against Michael Pharmacy Chain.

## Blockers / Risks
- None blocking. Everything across this entire thread (both `ennam.kg.go` and `LAAM` repos) remains **uncommitted** — user has not asked for a commit at any point across the whole multi-session thread.
