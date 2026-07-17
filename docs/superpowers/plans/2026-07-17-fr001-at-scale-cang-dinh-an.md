# FR-001 at Scale — Cảng Định An Measurement Plan

> ## ✅ Task 1 (substrate gate) ALREADY RUN — 2026-07-17. Read this before starting.
> **Project:** `Cảng Định An M&A` = `592c7ff7-9f6f-4cc5-9094-d9b3b685277e` — **stable, not re-ingested** (unlike Dasin, whose UUID churns). Still resolve by name if you re-run, but this ID held all session.
>
> **Corpus size — the "234 docs" figure is drafts, not documents.** `draft_nodes` = **234, all `processed`**; `canonical_document` = **77**; `document` nodes = **77**. The 234/77 ≈ **3.0×** ratio matches the recorded *"same PDF ingested 2–5× with divergent OCR"* — **dedup is working; 77 is the real unique-document count.** (Earlier notes saying "145 documents" are stale.)
>
> | Gate | Result | |
> |---|---|---|
> | chunks / embedded | **1005 / 1005** | ✅ |
> | OCR health (diacritics) | **93%** (938/1005) | ✅ predates the OCR bug's victims |
> | `similar_to` **before** | **133** (0.13 edges/chunk — 20× sparser than Dasin's 2.7) | 🔴 |
> | **linker run** → `similar_to` **after** | **3,258** (`edges_upserted: 4119`; histogram 0.85-0.90: 5248, 0.90-0.95: 4150) | ✅ **3.2 edges/chunk, matches Dasin** |
> | orphaned documents (no concept edge) | **13 / 77 = 17%** | ⚠️ see below |
>
> **The linker gate fired exactly as predicted** — `similar_to` had collapsed to 133 (memory records 1864 on 2026-07-13 at 626 chunks; chunks grew to 1005, edges fell). Measuring FR-001 before this would have "proven" expansion useless for entirely the wrong reason. **Post-linker smoke test:** `kg_graph_retrieve` → 20 rows, `expanded_count` 70, `hop_count` `[0,1]`, **13 distinct documents**, 20/20 with snippet text — far richer than Dasin's 6 docs, as expected at scale.
>
> **Two findings that change the plan below — do not skip:**
> 1. **This corpus is entity-rich, unlike Dasin.** `concept` 3694 · `organization` 1743 · `location` 1015 · `person` 693 · `artifact` 580 · `event` 268 · `document_chunk` 1005 · `document_section` 231. Dasin had **only `concept` (22)**. ⟹ the **6 resolved types exist here, so B1 entity resolution applies** — and the 95 `needs_review` dup hubs (`Công ty` deg 96, `Trị Vinh`=Trà Vinh, …) are live in this data and will distort any entity-based comparison. FR-001 is chunk-similarity, so it is not directly affected — but do not carry Dasin's "concept-only" assumptions across.
> 2. **The known contradiction is retrievable — in Vietnamese number format.** `14,71` → **4 chunks**, `33,6` → **2 chunks** (the B2 OCR fix). Searching `14.71`/`33.6` with a **dot** returns **0** — a decimal-separator trap that nearly produced a false "one side is missing" conclusion. **Worse, and directly relevant to the `contradiction-adjacent` class:** the same figure exists in **both** formats in the corpus — `122,81 ha`/`122,81ha`, `125,04 ha`/`125.04 ha`, `13,17 ha`/`13.17 ha`. That comma↔dot OCR noise is exactly the false-positive class a contradiction detector must suppress. Any query or matcher in this plan must handle both separators.
>
> **Remaining gate decision (Task 1 Step 4):** 13/77 documents have no concept edge. This corpus predates the extraction fail-loud fix, so those are likely the silent-empty-extraction class. **FR-001 is chunk-based and can proceed** — but the measurement's entity-adjacent claims are bounded by this, and it must be stated in the verdict.

*(Original plan below; header retained for the record — it said "145 docs", now measured at 77 unique / 234 drafts.)*

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Answer the one question Dasin could not: **at 145 documents, how often does 1-hop `similar_to` expansion rescue an answer that plain chunk search cannot reach — and is that frequency worth the precision cost?** This is the evidence gate on BA-033 Slice 2.

**Architecture:** Re-run the existing, proven `fr001_measure.py` against the Cảng Định An project with a corpus-appropriate query set. No new measurement machinery — the script is already correct and its one bug (document-id shape mismatch) is fixed. The only new work is the query set, the scale-specific metrics, and the relevance read.

**Tech Stack:** Python 3 stdlib (reuses `mcp_call.py` transport), the live DAAB bridge, Postgres for substrate checks.

## What Dasin already established (do not re-litigate)

**FR-001's mechanism is PROVEN.** See `mem:checkpoint/fr001-measurement-2026-07-17`. On query `"cơ quan nào cấp giấy phép đầu tư…"`, a **hop-1 edge-only** row (`7e83cedc`, BCTC2025 *"Báo cáo của Ban Giám đốc"*) carried the complete answer — both authorities, all three licences, dates — and `kg_search_chunks` **cannot reach that chunk at all**, not even when queried with the chunk's own verbatim phrasing (5 rows, `total_count: 5`, target absent). The k-cap confound was tested and ruled out.

**The mechanism, precisely:** the answer sentence sits in a chunk whose **aggregate embedding is about something else** (letterhead + addresses + management narrative). **query→chunk** similarity fails; **chunk→chunk** similarity from a topically-adjacent chunk succeeds. *Not* "recall without lexical match" (lexical overlap was strong); *not* "joining facts across documents".

**What is therefore NOT the question here.** Do not re-prove that expansion can work. **The open question is frequency and cost at scale:** at Dasin only **1 of 4** queries with `hop1_only_docs > 0` yielded a hop-1-only chunk that actually answered (`hop1_only_docs`=8, `true_cross_doc_hop1`=25 — the edge mechanism fires often but usually lands on documents already reachable). N=9 documents cannot distinguish "rare curiosity" from "load-bearing".

## Global Constraints
- **No LLM in the counting path.** This plan exists because a measurable question was handed to an LLM twice and it fabricated the numbers both times (`findings-dasin.md`, `findings-dasin-run2.md`, both banner-flagged COMPROMISED). The script counts; a human/LLM judges relevance **only** on the dumped snippets, **visibly separate** from the counting.
- **State predictions before running.** Each query is labelled with its predicted class in the script. A prediction that fails is a finding (Dasin's H1 broke the binary homo/hetero model — report that class of result, do not bury it).
- **A null result is a valid, valuable outcome.** If expansion rarely rescues answers at 145 docs, that **saves** the FR-002/003/005 build from resting on a false premise. Do not round a null up.
- **Resolve the project by name, never hardcode the UUID** — it changes on every re-ingest and a stale ID already cost one wrong-project detour.
- **`/other_projects/` is gitignored** — the script, raw output and report are **local artefacts**. The **Serena checkpoint is the only durable deliverable**.
- Cảng Định An is a **real M&A corpus** — do not paste document content into anything outside this workspace.

## File Structure
**Local (gitignored):**
- `other_projects/daab-sim-consumer/fr001_measure.py` (modify) — parameterise the query set + project; add the scale metrics in Task 3.
- `other_projects/daab-sim-consumer/queries-cangdinhan.py` (create) — the labelled query set.
- `other_projects/daab-sim-consumer/fr001-cangdinhan.md` + `-raw.txt` (create) — output.

**Tracked:**
- `.serena/memories/checkpoint/fr001-at-scale-<date>` (create via Serena MCP) — **the deliverable**.

---

## Task 1: Verify the substrate before measuring anything

**Files:** none. This is a gate — a bad substrate produces a meaningless null.

**Why this is Task 1:** Dasin's `similar_to` was **5 edges** after re-ingest until the linker was run manually (it is **not automatic**), which took it to 399. Measuring FR-001 on an unlinked corpus would "prove" expansion adds nothing — for entirely the wrong reason. `mem:backlog/ba033-slice2-readiness-path` records this exact trap: the FR-001 substrate was never generated for this project, and the harness misread it as a missing feature.

- [ ] **Step 1: Resolve the project + measure the substrate.**
```bash
PID=$(docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -c \
  "SELECT id FROM projects WHERE name LIKE 'Cảng Định An%';" | tr -d '\r')
echo "PID=$PID"
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT
 (SELECT count(*) FROM knowledge_nodes WHERE project_id='$PID' AND node_type='document')       AS documents,
 (SELECT count(*) FROM knowledge_nodes WHERE project_id='$PID' AND node_type='document_chunk') AS chunks,
 (SELECT count(e.node_id) FROM knowledge_nodes kn JOIN knowledge_node_embeddings e ON e.node_id=kn.id
   WHERE kn.project_id='$PID' AND kn.node_type='document_chunk')                               AS embedded,
 (SELECT count(*) FROM knowledge_edges WHERE project_id='$PID' AND edge_type='similar_to')     AS similar_to;"
```
Expected (from `mem:backlog/ba033-slice2-readiness-path`): ~145 documents, ~1005 chunks, **embedded == chunks**, `similar_to` in the hundreds/thousands.
- [ ] **Step 2: If `embedded < chunks` or `similar_to == 0`, STOP and fix the substrate first.** Run the linker: `curl -s -X POST http://localhost:8082/api/v1/internal/graphrag/link -H "Authorization: Bearer $KG_API_KEY" -H "Content-Type: application/json" -d "{\"project_id\":\"$PID\"}"` → expect `edges_upserted` in the hundreds+. Re-check Step 1. **Record both numbers (before/after) in the checkpoint** — "the linker had not been run" is itself a finding about operational readiness.
- [ ] **Step 3: Sanity-check corpus health** (a garbage corpus invalidates the measurement, as the OCR bug did on Dasin):
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT count(*) AS chunks,
 count(*) FILTER (WHERE properties->>'content' ~ '[àáảãạăâđèéẻẽẹêìíỉĩịòóỏõọôơùúủũụưỳýỷỹỵÀÁẢÃẠĂÂĐÈÉÊÌÍÒÓÔƠÙÚƯÝ]') AS with_diacritics
FROM knowledge_nodes WHERE project_id='$PID' AND node_type='document_chunk';"
```
Expected ≥85% (this corpus measured **93%** — it predates the OCR bug's victims). **If materially lower, stop** — re-ingest through the fixed pipeline first, or the measurement measures OCR damage.
- [ ] **Step 4: Check for orphaned documents** (the extraction-fail-loud fix is newer than this corpus's ingest):
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT count(*) FROM knowledge_nodes d WHERE d.project_id='$PID' AND d.node_type='document'
AND NOT EXISTS (SELECT 1 FROM knowledge_edges e WHERE e.source_id=d.id AND e.edge_type='mentions');"
```
Any count > 0 = documents invisible to entity tools. **Record it; it bounds what the measurement can claim** (it does not necessarily block the run — FR-001 is chunk-similarity, not entity-based — but a corpus with orphans is not a clean baseline).

---

## Task 2: Build the query set — the part that decides whether this run means anything

**Files:** create `other_projects/daab-sim-consumer/queries-cangdinhan.py`.

**Interfaces:** exports `QUERIES: list[tuple[str, str, str, str]]` = `(id, predicted_class, query, prediction_rationale)`, consumed by `fr001_measure.py`.

**Why this task carries the risk:** the metric is only as good as the queries. Dasin's set was 10; at 145 documents a handful of queries could miss the effect entirely or manufacture it. And Dasin **falsified the binary class model** — H1 ("doanh thu thuần…", predicted homogeneous/no-gain) surfaced 2 hop-1-only cross-document hits on licence documents. **Do not just port the Dasin labels.**

- [ ] **Step 1: Ground the queries in what is actually in this corpus.** Do **not** invent DD questions from imagination — read the real entity/document inventory first:
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT left(title,60) FROM knowledge_nodes WHERE project_id='$PID' AND node_type='document' LIMIT 40;"
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT node_type, count(*) FROM knowledge_nodes WHERE project_id='$PID' GROUP BY 1 ORDER BY 2 DESC;"
```
Known corpus facts (`mem:backlog/ba033-slice2-readiness-path`): 145 documents — hợp đồng hợp tác, FS 2022, ĐTM (environmental impact), CV Sở Xây dựng, kho xăng dầu. Known real cross-document contradiction: **14.71ha vs 33.6ha phase-2 area** (planning decision vs 2019 Sở Xây dựng letter) — found only by manual cross-reading. Known entity mess: dup/OCR-mangled hubs (`Công ty` deg 96, `Công ty TNHH Xây dựng Flàm Giang` = Hàm Giang, `UBND TÍNH TRÀ VINH`, `Cục llàng hải` = Hàng hải, `Trị Vinh` = Trà Vinh) — **95 `needs_review` items**.

- [ ] **Step 2: Write ~20-25 queries in three labelled classes.** More than Dasin's 10 — at 145 documents the per-query variance is higher, and the decision rides on frequency.
  - **`buried`** (~8) — the class the Dasin instance proved. Queries whose likely answer sits in a **narrative/summary section of a document that is *about* something else** (a management report, a preamble, a covering letter summarising approvals). **Prediction: expansion rescues.** This is the hypothesis under test.
  - **`homogeneous`** (~8) — answers in lexically-similar, topically-dedicated documents (FS figures, ĐTM standard sections). **Prediction: expansion adds nothing.**
  - **`contradiction-adjacent`** (~5) — probing the known 14.71ha/33.6ha area conflict and similar. **Prediction: expansion improves *recall of both sides*, but does not flag the conflict** (Dasin showed retrieval ≠ reconciliation). This tests a *negative* prediction, which is how the FR-005 decision gets its evidence.
  Each entry carries its rationale **in the file, written before the run**.

- [ ] **Step 3: Peer-check the set against the falsification risk.** For each `homogeneous` query ask: *"is there any plausible narrative document that also summarises this?"* If yes, it is not homogeneous — relabel or drop. Dasin's H1 failed exactly this check post-hoc; do it **before** running.

---

## Task 3: Extend the script with the metrics scale actually needs

**Files:** modify `other_projects/daab-sim-consumer/fr001_measure.py`.

**Interfaces:** keep the existing per-query metrics (`gr_rows`, `sc_rows`, `gr_docs`, `sc_docs`, `gr_only_docs`, `hop1_rows`, `hop1_only_docs`, `true_cross_doc_hop1`, `dropped_count`, `expanded_count`). **Do not change their definitions** — comparability with the Dasin baseline is the point.

> **Read `fr001_measure.py` before editing.** Note its one hard-won correction: `kg_search_chunks` nests `document_id` under `properties.document_id` while `kg_graph_retrieve` puts it top-level — the `doc_id_of()` helper handles both. An earlier cut assumed one shape and silently inflated `gr_only_docs` from ~13 to 55. **Do not regress this.**

- [ ] **Step 1: Add `--project` and `--queries` args** so the script runs against either corpus without editing code. Default to the existing Dasin behaviour so the baseline stays re-runnable.
- [ ] **Step 2: Add the scale metrics.**
  - **`hop1_only_rate`** = queries with `hop1_only_docs > 0` / total queries. **The headline.** Dasin baseline: **4/10 = 0.40**.
  - **`answer_rate`** (filled in by the Task 4 human read, not the script) = hop-1-only chunks that actually answer / hop-1-only chunks read. Dasin baseline: **1/4 queries**.
  - **`redundancy_ratio`** = `true_cross_doc_hop1 / hop1_only_docs` — how often the edge fires but lands somewhere already reachable. Dasin: **25/8 ≈ 3.1**. **If this rises sharply at 145 docs, expansion is mostly doing redundant work.**
  - **Per-class breakdown** of all of the above.
- [ ] **Step 3: Cap the snippet dump.** At 145 docs × 25 queries the dump will be enormous. Dump **only hop-1-only rows** (the ones needing judgement), max ~40 total, with `document_id`, score, and the chunk text. The full raw JSON still goes to `-raw.txt`.
- [ ] **Step 4: Self-check the script on the Dasin project first.** Run with `--project Dasin --queries queries-dasin` and confirm it reproduces the recorded baseline (`hop1_only_docs`=8, `true_cross_doc_hop1`=25, 4/10 queries). **If it does not reproduce, the script changed behaviour — fix that before touching Cảng Định An.** This is the regression guard.

---

## Task 4: Run, judge, decide

- [ ] **Step 1: Run against Cảng Định An.**
```bash
cd other_projects/daab-sim-consumer
export KG_API_KEY=<live admin key>
export KG_PROJECT_ID=$PID          # from Task 1, resolved by name
python3 fr001_measure.py --project "Cảng Định An M&A" --queries queries-cangdinhan | tee fr001-cangdinhan-raw.txt
```
- [ ] **Step 2: The relevance read — the only place a judgement belongs.** For each dumped hop-1-only snippet, answer **one** question: *does this chunk contain the answer to its query?* Yes/No/Partial, one line of justification each. **Rules learned the hard way:**
  - Judge the **snippet as returned**, not what you know the corpus contains.
  - "Right document class, no answer" is a **No** — Dasin's X2 (`bb7d05cf`, GCNĐKKD branch cert) was the right document for the capital question but carried no capital figure.
  - **Test the k-cap confound on every Yes.** For each hop-1-only chunk that answers, verify `kg_search_chunks` genuinely cannot reach it — query it with **the chunk's own verbatim phrasing** and check `total_count` and whether the doc appears. On Dasin this is what turned a plausible claim into proof. **A Yes without this check does not count.**
- [ ] **Step 3: Write `fr001-cangdinhan.md`** — per-query table, per-class aggregates, the three scale metrics vs the Dasin baseline, the snippet judgements, and **one** verdict:
  - **LOAD-BEARING** — `hop1_only_rate` holds or rises **and** `answer_rate` is materially > 0 with confounds ruled out ⟹ FR-001 matters at scale; it is the retrieval floor for FR-002/003/005.
  - **MARGINAL** — the mechanism fires but rarely answers, and `redundancy_ratio` is high ⟹ keep it, do not build on it.
  - **NOT LOAD-BEARING** — `hop1_only_docs` collapses at scale ⟹ a real, valuable null; FR-002/003/005 must not assume graph expansion as its retrieval floor.
- [ ] **Step 4: Checkpoint (the durable deliverable).** `mcp__serena__write_memory("checkpoint/fr001-at-scale-<YYYY-MM-DD>", …)`: the verdict, all three metrics vs Dasin, the query set + predictions (including any that **failed** — Dasin's H1 did), substrate numbers from Task 1, and the confound checks. Update `mem:backlog/ba033-slice2-readiness-path` with the FR-001 verdict — that backlog's item 3 has been waiting on exactly this.

---

## Self-Review

- **Coverage:** substrate gate (the trap that already fooled one harness) → Task 1. Query set grounded in the real corpus, with pre-stated predictions → Task 2. Scale metrics + a regression guard against the Dasin baseline → Task 3. Run, judgement, verdict, durable record → Task 4. ✓
- **What this plan refuses to re-do:** re-proving the mechanism. Dasin settled that with a confound-tested instance. Scope is **frequency and cost at 145 documents** — the only open variable.
- **Type/contract consistency:** metric definitions unchanged from `fr001_measure.py` (comparability is the whole point); `doc_id_of()`'s dual-shape handling preserved (Task 3 read-before-write note); `kg_graph_retrieve` params `result_k`/`include_snippet` — **there is no `limit`**; project resolved by name.
- **Deliberately out of scope:** the 95 `needs_review` dup-entity hubs, `kg_get_context` 404s, `kg_related_documents` centrality/IDF, typed edges, the contradiction layer. Several are probably real; **all were surfaced by compromised runs and must be re-verified by direct measurement before they earn a plan.** The `contradiction-adjacent` class (Task 2) will produce *measured* evidence for the FR-005 decision as a by-product — that is the honest way to feed it.
- **Risks:**
  - **The corpus predates the OCR + extraction fixes.** Task 1 Steps 3-4 gate on this. If it is dirty, the measurement measures dirt — the exact error that made the first Dasin harness worthless. Re-ingesting 145 documents is expensive; **decide explicitly, do not drift into measuring a broken corpus.**
  - **Query-set bias is the dominant threat.** 25 queries chosen by the same person who states the predictions can manufacture either outcome. Task 2 Step 3's falsification check is the guard; state plainly in the verdict that the set is judgement-selected and non-exhaustive.
  - **A null is success.** If expansion collapses at scale, this plan has saved a large build. Say so; do not soften it.
