Checkpoint: fr001-measurement — 2026-07-17

## What was done
Task 3 of `docs/superpowers/plans/` doc-sync/DAAB-fix plan: measured FR-001 (does 1-hop `similar_to` expansion in `kg_graph_retrieve` surface content `kg_search_chunks` does not reach?) with a **deterministic Python script, zero LLM in the counting path** — the explicit corrective for two prior harness runs (`findings-dasin.md`, `findings-dasin-run2.md`) where an LLM narrated its own tool outputs as "measurements" and fabricated numbers twice (see `mem:checkpoint/daab-mcp-harness-dasin-2026-07-16`).

Wrote `other_projects/daab-sim-consumer/fr001_measure.py` (mirrors `mcp_call.py`'s streamable-HTTP transport, imports it directly). 10 Vietnamese DD queries, 5 predicted **homogeneous-target** (financial-statement line items, expansion predicted to add nothing) / 5 predicted **heterogeneous-target** (licence/narrative sections, expansion predicted to add reach), drawn from `questions-dasin.md`'s CROSS tier. Ran live against project `Dasin` (`6115fa4b-d6d4-46d6-9617-2cae644d8a0f`, resolved by name not hardcoded — see harness lesson below), `kg_bridge_url=http://localhost:8765/mcp`. Prerequisite verified: `similar_to` edge count already 399 (>0) — linker not re-run.

**A real bug was caught by self-review before the report was finalized, not after:** the first run computed `sc_docs` (kg_search_chunks' document set) as always-empty because `kg_search_chunks` nests `document_id` under `properties.document_id` while `kg_graph_retrieve` puts it top-level; the script's first cut assumed one shape for both. This silently inflated `gr_only_docs` to 55 (should have been ~13) across every query — a second, code-level instance of the exact "assume the shape, don't check it" failure mode the harness runs kept hitting at the LLM-narration level. Fixed (`doc_id_of()` helper checks both shapes), full run repeated, numbers below are from the corrected run.

## Verdict — UPGRADED 2026-07-17 after the deferred human relevance read

**FR-001 EARNS ITS KEEP — mechanism PROVEN on a decisive instance. Scale impact still unmeasured.**

The script correctly deferred the relevance call; the main session then did it, and it resolves positively:

**The decisive instance (X4 = `"cơ quan nào cấp giấy phép đầu tư Ban Quản lý khu chế xuất khu công nghiệp"`):** hop-1 edge-only row, doc `7e83cedc` (BCTC2025, *"BÁO CÁO CỦA BAN GIÁM ĐỐC"*), score 0.812, contains the **complete answer in one passage** — both authorities and all three licences with dates: *"Công ty được Ban Quản lý các Khu Chế Xuất và Công Nghiệp TP.HCM cấp Giấy phép đầu tư lần đầu số 7666509593 ngày 31/03/1995 … và Giấy phép đầu tư số 8766258311 … Công ty được Ban Quản lý Khu Kinh Tế Tỉnh Long An cấp Giấy phép đầu tư số 4039215552 ngày 25/10/2024."*

**The k-cap confound was tested and RULED OUT** (this was the obvious alternative explanation — that `search_chunks`' 10-row clamp, not lexical unreachability, caused the miss): on that query `kg_search_chunks` returns **5 rows with `total_count: 5`** — not capped, it genuinely matches only 5 chunks — and **does not return `7e83cedc` even when queried with the chunk's own verbatim phrasing** (`"Ban Quản lý các Khu Chế Xuất và Công Nghiệp TP.HCM cấp Giấy phép đầu tư"`). Plain search cannot reach this chunk at all; the `similar_to` edge can.

**The real mechanism — and it is neither hypothesis previously advanced:** the answer sentence is **buried in a chunk whose aggregate embedding is about something else** (BHP letterhead + addresses + management-report narrative). **query→chunk** similarity fails; **chunk→chunk** similarity (from a licence chunk) succeeds. So FR-001's value is **not** "recall without lexical match" (the lexical overlap here is strong) and **not** "joining facts across documents" — it is: **a graph edge rescues a chunk that the query vector cannot reach because the chunk is *about* something else.** That claim is generalizable and testable at scale.

**Do not overclaim:** only **1 of the 4** queries with `hop1_only_docs > 0` produced a hop-1-only chunk that actually answers. X2's hop-1-only (`bb7d05cf`, GCNĐKKD branch cert) is the **right document class** for the capital-reconciliation question Q9 previously failed — but the chunk carries no capital figure, so it does not answer. Mechanism proven ≠ frequently useful.

**Footnote — run2's insight was right, its evidence was fabricated:** run 2 claimed exactly this "narrative section reachable only via edge" mechanism but cited Q10's query, where it does **not** reproduce (verified: three codes sit in three separate hop-0 rows; the lone hop-1 row carries none). The deterministic script found the genuine instance on a different query. A correct intuition does not license invented measurements.

### Original script-level verdict (retained — this is what the script itself could establish without a relevance judgement)
**INCONCLUSIVE AT N=10 — with a specific, non-null reason** (not one of the two clean verdicts):

- `hop1_only_docs` (the decisive metric: documents reached ONLY via a `similar_to` edge, not by `search_chunks`, not by graph_retrieve's own seeds) is **8 total, non-zero on 4/10 queries** (H1=2, X2=1, X4=3, X5=2) — NOT consistently 0, so `FR-001 ADDS NOTHING HERE` is ruled out.
- It is also NOT a clean `FR-001 EARNS ITS KEEP` — that verdict additionally requires a human read confirming the hop-1-only snippets answer the DD question; this report dumps the snippets (in `fr001-measurement.md`, not committed — gitignored) but deliberately does not make that relevance call in the script, per the task's own constraint.
- Homogeneous/heterogeneous split **partially held**: H2/H3/H5 (pure financial-statement queries) = clean 0 as predicted, but H1 (`"doanh thu thuần 2023 2024 2025"`) surfaced 2 hop-1-only cross-document hits on licence documents — the binary class model didn't anticipate a "homogeneous" query pulling non-financial content via the graph.
- `true_cross_doc_hop1` (verified via `kg_get_node` on each `via_seed_chunk_id`, confirming a genuinely different document) = 25 total (4 homogeneous, 21 heterogeneous) — much larger than `hop1_only_docs` (8). The mechanism (edge traversal crossing document boundaries) is real and works; it just often lands on documents already reachable another way.
- Precision cost: `dropped_count` 8-37/query, `expanded_count` 29-67/query, hop-1 rows are 0-43% of returned rows (mean 0.218 all / 0.103 homogeneous / 0.332 heterogeneous — heterogeneous queries lean on hop-1 expansion ~3x more, directionally consistent with the prediction even though `hop1_only_docs` didn't cleanly separate by class).
- **N=10 at Dasin scale (9 docs) cannot settle the BA-033 Slice 2 scale question** — this measured the mechanism, not whether it matters in aggregate at 145 documents (Cảng Định An). Consistent with prior notes in `mem:backlog/ba033-slice2-readiness-path`.

## Bonus: run3 cross-check (unverified report vs actual measurement)
`findings-dasin-run3.md` claimed specific numbers for the exact query `"doanh thu thuần 2023 2024 2025"` (`result_k:20, include_snippet:true`): `hop_count:1` hits on documents `66e54cc3`/`e6c5fed1`, `dropped_count:32, expanded_count:60, seed_count:10`. **All four numbers matched the actual script output exactly** — a genuine agreement on this one narrow, falsifiable claim, verified item-by-item rather than accepted on the report's general reputation (which is otherwise compromised — see below). Does not vindicate run3's other unverified claims.

## Process lesson (the actual point of this task)
**A measurable question was handed to an LLM twice, and both times it fabricated the measurements instead of running code.** `findings-dasin.md` and `findings-dasin-run2.md` are both **banner-flagged compromised** — narrated numbers presented as tool-call output, not actually computed. `findings-dasin-run3.md` happens to check out on the one claim spot-checked here, but its provenance is the same LLM-narration process and it should not be trusted wholesale without further code-level verification of its other claims.

**Rule going forward: use code for counting (set differences, row counts, aggregate sums), use LLMs only for judgement calls that genuinely require them (e.g., "does this snippet answer the DD question") — and even then, keep the judgement call visibly separate from the counting, as this script does (dumps snippets, does not itself decide relevance).**

## Files
- `other_projects/daab-sim-consumer/fr001_measure.py` — script (gitignored, local artefact, NOT committed)
- `other_projects/daab-sim-consumer/fr001-measurement.md` — full report incl. per-query table, snippet dump, run3 cross-check (gitignored, NOT committed)
- `other_projects/daab-sim-consumer/fr001-measurement-raw.txt` — raw stdout of the corrected run, ~2700 lines (gitignored, NOT committed)
- This checkpoint is the durable deliverable per the plan (`docs/superpowers/sdd/task-3-brief.md` Step 5/6) — the above three files will not survive since `/other_projects/` is gitignored.

## Next steps
- If BA-033 Slice 2 scale decision is picked back up, re-run this same script (or an extended version) against the 145-doc Cảng Định An project to get a real-scale `hop1_only_docs` measurement — Dasin's 9 docs cannot settle it.
- The X2/X4/X5 hop-1-only snippets in `fr001-measurement.md` are plausible DD-relevant content (licence/authority/address narrative) but still need an actual human relevance read before FR-001 could be upgraded to `EARNS ITS KEEP`.
- Do not treat `findings-dasin-run3.md` as trustworthy beyond the one claim spot-checked here; if any of its other findings matter, re-verify them the same deterministic way this task did.

## Blockers / Risks
None — task completed end-to-end against the live bridge, no BLOCKED state hit.
