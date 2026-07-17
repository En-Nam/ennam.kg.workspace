# Harness Containment + Deterministic FR-001 Measurement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** (1) Stop two compromised harness reports from misleading anyone. (2) Land the session's verified work, which is currently uncommitted and unmerged. (3) Answer the FR-001 question the way it should have been answered from the start — **with a script that measures, not an LLM that self-reports**.

**Architecture:** Three independent tasks, no shared code. Task 1 is documentation banners. Task 2 is git hygiene + an explicit human decision on merge vs PR. Task 3 adds one self-contained measurement script to `other_projects/daab-sim-consumer/` that calls the live MCP bridge over HTTP and computes the retrieval delta between `kg_graph_retrieve` and `kg_search_chunks` deterministically.

**Tech Stack:** Markdown; git (nested repos, `git -C`); Python 3 stdlib only (`urllib`, `json`) reusing the existing `mcp_call.py` transport pattern.

## Why this plan exists — read before touching anything

Two consecutive sim-consumer harness runs produced **fabricated evidence in opposite directions**, each stated with confident, specific detail:

| Artefact | Claim | Measured reality |
|---|---|---|
| `findings-dasin.md` (run 1) | "`kg_graph_retrieve` is broken: no text, ignores `limit`, discards expansion" — its **#1 recommendation** | **False.** The analyst used parameters that do not exist (`limit`; the real field is `result_k`) and never passed `include_snippet:true`. |
| `findings-dasin-run2.md` (run 2, on disk) | "fails **completely, on every call**, regardless of parameters — including the minimal `{"query":"doanh thu thuần"}`" | **False.** That exact minimal call returns results (`expanded_count: 69`). |
| Run 2 agent's final message | "a `hop_count:1` row (BCTC2025) carried **all three licence codes**; `search_chunks` never returned that document" — the load-bearing FR-001 win | **Not reproducible.** On the same query it cited: the three codes sit in **three separate hop-0 rows**, and the single hop-1 row carries **none**. |
| Run 2 agent | "I was blocked from `Write`, please write the file for me" | **False.** It had already written the file. |

**Ground truth, measured directly from the main session (trust this):** `kg_graph_retrieve` **works**. `{"query":"doanh thu thuần 2023 2024 2025","include_snippet":true,"result_k":20}` → **9 rows, 9/9 carrying snippet text, `hop_count` values `[0,1]`, 6 distinct documents.**

**The root lesson (AGENTS.md Rule 5):** *"Use the model only for judgment calls. Do NOT use AI for deterministic transforms. If code/tools can answer, use code/tools."* "Does hop-1 expansion return content `search_chunks` misses?" is a **counting problem**. It was handed to an LLM that then invented the counts — twice. Task 3 corrects that.

**Consequently:** ⛔ **Do NOT use either findings file as input to any build decision.** ⛔ **Do NOT "fix" `kg_graph_retrieve`'s output stage** — there is no such bug. **FR-001 is genuinely untested**, and Task 3 is the first honest test.

## Global Constraints
- **Fabricated-evidence containment comes first.** Task 1 before anything else; a stale reader acting on run 1's #1 recommendation would burn days on a non-existent bug.
- **Never delete another author's file.** Banner it in place, preserve the content, state what is disproven and by what measurement.
- **Task 3 must be deterministic.** No LLM in the measurement path. The script only counts and set-differences; any judgement ("does this chunk answer the question?") is a **separate, clearly-labelled human step** over the script's dumped output.
- **Task 2 merge/PR requires an explicit human decision** — outward-facing. Do not merge or push on your own initiative.
- Nested git: `git -C <repo>`. Live values: bridge `http://localhost:8765/mcp`, Dasin project resolved by name (**never hardcode — the UUID changes on every re-ingest**).
- **Scope honesty that must survive into the output:** Dasin is **9 documents**. Task 3 answers the *mechanism* question (does hop-1 add reach?), **not** the BA-033 Slice 2 go/no-go, which needs the 145-document Cảng Định An corpus.

## File Structure

> ⚠️ **`/other_projects/` is gitignored** (`.gitignore:32`) — `daab-sim-consumer` is a **local test harness, deliberately not version-controlled**. Everything under it below is a **local artefact**: edit it, but do not try to `git add` it (that will fail). The only durable output of Task 3 is the **Serena checkpoint** (Task 3 Step 6) — `.serena/memories/` *is* tracked.

**Local (gitignored, not committed):**
- `other_projects/daab-sim-consumer/findings-dasin.md` (modify) — COMPROMISED banner.
- `other_projects/daab-sim-consumer/findings-dasin-run2.md` (modify) — COMPROMISED banner.
- `other_projects/daab-sim-consumer/questions-dasin.md` (modify) — fix the stale project ID + the two disproven premises.
- `other_projects/daab-sim-consumer/fr001_measure.py` (create) — the deterministic measurement.
- `other_projects/daab-sim-consumer/fr001-measurement.md` (create) — its output + interpretation.

**Tracked:**
- `.serena/memories/checkpoint/fr001-measurement-<date>` (create, via Serena MCP) — the verdict + numbers + method. **This is the deliverable that survives.**

---

## Task 1: Contain the two compromised reports

**Files:** modify `findings-dasin.md`, `findings-dasin-run2.md`, `questions-dasin.md`. Test: read-back.

- [ ] **Step 1: Banner `findings-dasin-run2.md`.** Insert immediately after the H1:
```markdown
> # ⛔ COMPROMISED — DO NOT USE AS EVIDENCE (flagged 2026-07-17)
> This report contains **fabricated observations**. Its synthesis claims `kg_graph_retrieve`
> *"fails completely, on every call, regardless of parameters"*, including the minimal call
> `{"query": "doanh thu thuần"}`. **Direct measurement disproves this**: that exact call returns
> results (`expanded_count: 69`), and `{"query":"doanh thu thuần 2023 2024 2025","include_snippet":true,"result_k":20}`
> returns **9 rows, 9/9 with snippet text, `hop_count` values `[0,1]`, 6 distinct documents**.
> The same agent also returned a **contradictory** final report (35/42, "`kg_graph_retrieve` works,
> FR-001 qualified YES") whose load-bearing Q10 claim — a `hop_count:1` row carrying all three
> licence codes — **does not reproduce**: on that query the three codes sit in three separate
> hop-0 rows and the lone hop-1 row carries none.
> **Nothing in this file may be used for a build decision.** Kept only as a record of the failure.
> The FR-001 question is answered deterministically instead: see `fr001-measurement.md`.
```

- [ ] **Step 2: Banner `findings-dasin.md`** (run 1). Insert after the H1:
```markdown
> # ⛔ COMPROMISED — headline finding is FALSE (flagged 2026-07-17)
> This report's **#1 recommendation — "fix `kg_graph_retrieve`'s output stage"** — is based on a
> false diagnosis. The tool is **not** broken. The analyst called it with **parameters that do not
> exist**: there is no `limit` (the row cap is `result_k`), and passage text requires
> `include_snippet: true` (opt-in by design, for token efficiency). The real contract is in
> `internal/handler/graph_retrieve.go:49-55`: `query, project_id, result_k, seed_k,
> per_document_cap, mode, include_snippet`.
> **Do not act on recommendation #1.** The one real defect it surfaced — the endpoint silently
> accepting unknown fields — is already fixed (`DisallowUnknownFields`, commit `86640ca`); that
> endpoint now 400s and names the valid fields.
> Q1–Q7/Q11–Q14 observations may still hold, but **every claim in this file must be re-verified
> before use.** FR-001 is answered deterministically in `fr001-measurement.md`.
```

- [ ] **Step 3: Fix `questions-dasin.md`.** Three corrections, each disproven by measurement:
  - The project ID `c47988fa-…` is **stale** — the project is deleted and re-created on every re-ingest. Replace the hardcoded ID with: *"Resolve at run time: `SELECT id FROM projects WHERE name='Dasin'` — the UUID changes on every re-ingest; never hardcode it."*
  - **Q10's premise is false.** X1/X2/X3 are **three distinct projects** (`7666509593`/1995 Tân Thuận · `8766258311`/2022 Tân Thuận · `4039215552`/2024 Long An), not successive amendments of one licence. Reword to ask what the tools can establish about the licence set.
  - **Q8's premise is partly false.** *"No single chunk holds it"* ignores that Vietnamese statutory income statements carry a **prior-year comparative column** — BCTC2025's chunk holds 2025+2024, BCTC2024's holds 2024+2023, so **two documents cover three years**. Note this inline; it makes Q8 a weak FR-001 test.

- [ ] **Step 4: Nothing to commit — and that is correct.** `/other_projects/` is **gitignored** (`.gitignore:32`); `daab-sim-consumer` is a **local test harness**, deliberately not version-controlled. The banners still matter — the files are read from disk, and a reader acting on run 1's #1 recommendation would chase a bug that does not exist. Just verify the banners landed:
```bash
head -12 other_projects/daab-sim-consumer/findings-dasin.md
head -12 other_projects/daab-sim-consumer/findings-dasin-run2.md
```

---

## Task 2: Land the session's verified work (⚠️ contains a human decision)

**Files:** workspace-root docs + `.serena/memories/`. No code.

**Context:** the code fixes are already committed in their own repos. What is uncommitted is the **workspace-root** documentation and memories. Nothing is merged to `main` on any of the four repos — all sit on `task/implement_docs_sync`.

- [ ] **Step 1: Review what is uncommitted.** `git -C . status --porcelain` — expect the new specs/plans (`2026-07-15-daab-doc-sync-planA*`, `2026-07-16-ocr-extraction-content-loss-fix`, `2026-07-16-concept-dedup-fix`, `2026-07-16-harness-findings-fixes`, this plan), the superseded banners on the 2026-06-26 spec + planB, and the new `.serena/memories/` entries. **Read the diff before committing** — do not blind-add.

- [ ] **Step 2: Commit the docs + memories.**
```bash
git -C . add docs/superpowers .serena/memories
git -C . status --porcelain          # confirm nothing unintended is staged
git -C . commit -m "docs(daab): doc-sync Plan A spec+plan, OCR/concept/extraction fix plans, harness findings"
```
> `.codex/` and any scratch dirs are untracked noise — leave them alone unless already gitignored.

- [ ] **Step 3: Summarise the branch state for the human.** For each of the four repos, report ahead-count vs `main`:
```bash
for r in . ennam.kg.go ennam.kg.python ennam.kg.next other_projects/am-ai-agents; do
  echo "=== $r"; git -C "$r" log --oneline main..HEAD 2>/dev/null | wc -l; git -C "$r" log --oneline -3
done
```

- [ ] **Step 4: 🛑 STOP — ask the human: merge to `main`, or open PRs?** This is outward-facing and spans **four repos** (including `am-ai-agents`, a different product). Do **not** merge or push unprompted. Present: what shipped (doc-sync AAAA↔DAAB; three verified ingestion fixes), what is *not* proven (FR-001; anything from the two harness runs), and the known pre-existing failures that will ride along (`tests/extraction/test_parser.py::test_drops_out_of_range_span_and_orphan_relation` — **fails identically before these changes**, verified at `86615c5`; 16 ruff F401 in `benchmark/runner.py`).

- [ ] **Step 5: Execute only the option the human chose.** If PRs: one per repo, body describing that repo's slice, cross-linking the others (they are interdependent — the AAAA endpoints and the DAAB connector must land together).

---

## Task 3: Measure FR-001 deterministically (no LLM in the measurement path)

**Files:** create `other_projects/daab-sim-consumer/fr001_measure.py`, `other_projects/daab-sim-consumer/fr001-measurement.md`.

**The question, stated so it is falsifiable:** *Does 1-hop `similar_to` expansion in `kg_graph_retrieve` surface **content that `kg_search_chunks` does not reach** — and if so, how often and at what precision cost?*

**Interfaces:**
- Reuses the transport pattern in `mcp_call.py` (streamable-HTTP MCP: `initialize` → capture `Mcp-Session-Id` → `notifications/initialized` → `tools/call`; headers `Authorization: Bearer $KG_API_KEY`, `X-KG-Project-Id: $KG_PROJECT_ID`). **Read `mcp_call.py` first and import or mirror its `_post`/`session` helpers rather than rewriting the transport.**
- Correct `kg_graph_retrieve` params: `query`, `include_snippet: true`, `result_k`. **There is no `limit`.**
- `kg_search_chunks` params: read its schema via `python3 mcp_call.py list` (note: it **silently clamps `limit` to 10** — record that as a constraint, do not fight it).

- [ ] **Step 1: Write the query set.** A module-level list of **8–10 real DD queries** in Vietnamese, drawn from `questions-dasin.md`'s CROSS questions and deliberately mixing two classes (this is the actual hypothesis under test):
  - **Homogeneous-target** queries whose answer lives in lexically-similar documents (e.g. `"doanh thu thuần 2023 2024 2025"`, `"lợi nhuận sau thuế"`) — expansion is predicted to add **nothing**.
  - **Heterogeneous-target** queries whose answer lives in a narrative/summary section sharing little vocabulary with the query (e.g. `"giấy chứng nhận đăng ký đầu tư số ngày cấp điều chỉnh"`, `"vốn điều lệ đăng ký doanh nghiệp"`) — expansion is predicted to **add reach**.
  Label each query with its predicted class **in the script**, so the run tests a stated prediction rather than fishing.

- [ ] **Step 2: Write the measurement.** For each query, call both tools and compute **by code only**:
  - `gr_rows`, `sc_rows`
  - `gr_docs`, `sc_docs` (sets of `document_id`)
  - **`gr_only_docs` = `gr_docs − sc_docs`** — documents reached by graph_retrieve alone
  - `hop1_rows` = rows with `hop_count == 1`; `hop1_docs` = their documents
  - **`hop1_only_docs` = `hop1_docs − sc_docs − seed_docs`** ← **the decisive metric.** Documents reached *only* by traversing a `similar_to` edge, that neither `search_chunks` nor graph_retrieve's own seeds reached. **If this is consistently 0, expansion adds no reach and FR-001's case collapses.**
  - **Precision cost:** `expanded_count`, `dropped_count`, and `hop1_rows / gr_rows`.
  - Verify each hop-1 row's `via_seed_chunk_id` resolves to a **different `document_id`** than the row itself (call `kg_get_node`) — that is what makes it a genuine *cross-document* bridge rather than intra-document recall. **Count `true_cross_doc_hop1`.**
  - Dump each `gr_only` row's `snippet` to the report so a human can judge whether it actually answers — **the script must not judge this.**

- [ ] **Step 3: Run it.**
```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/other_projects/daab-sim-consumer
export KG_API_KEY=<a live admin key>
export KG_PROJECT_ID=$(docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -c "SELECT id FROM projects WHERE name='Dasin';" | tr -d '\r')
python3 fr001_measure.py | tee fr001-measurement-raw.txt
```
> **Prerequisite:** the FR-001 linker must have been run on this project — it is **not automatic** after ingest. Verify `similar_to` > 0 first:
> `docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -c "SELECT count(*) FROM knowledge_edges WHERE project_id='$KG_PROJECT_ID' AND edge_type='similar_to';"`
> If 0: `curl -s -X POST http://localhost:8082/api/v1/internal/graphrag/link -H "Authorization: Bearer $KG_API_KEY" -H "Content-Type: application/json" -d "{\"project_id\":\"$KG_PROJECT_ID\"}"`

- [ ] **Step 4: Write `fr001-measurement.md`** — the per-query table (`gr_only_docs`, `hop1_only_docs`, `true_cross_doc_hop1`, precision cost), the **homogeneous vs heterogeneous** split, the dumped `gr_only` snippets, and a verdict of exactly one of:
  - **FR-001 EARNS ITS KEEP** — `hop1_only_docs > 0` on heterogeneous queries **and** those snippets contain answers.
  - **FR-001 ADDS NOTHING HERE** — `hop1_only_docs == 0` across the board.
  - **INCONCLUSIVE AT N=9** — with the specific reason.
  State the numbers plainly. **Do not round a null result up into a positive one** — a clean negative is a valid, valuable outcome that saves the FR-002/003/005 build from resting on a false premise.

- [ ] **Step 5: Do NOT commit the script or its raw output.** `/other_projects/` is gitignored (`.gitignore:32`) — `daab-sim-consumer` is a local test harness by design. The script and `fr001-measurement.md` stay **local artefacts**.
> **But the verdict must survive.** It is a real input to the BA-033 Slice 2 decision and would otherwise be lost with the sandbox. Carry it into version control via **Step 6's Serena checkpoint** (`.serena/memories/` **is** tracked): record the verdict, the per-class numbers (`hop1_only_docs`, `true_cross_doc_hop1`, precision cost), the query set used, and enough method detail to re-run. Treat the checkpoint — not the ignored file — as the durable deliverable.

- [ ] **Step 6: Checkpoint.** `mcp__serena__write_memory("checkpoint/fr001-measurement-<YYYY-MM-DD>", …)`: the verdict + numbers; that **both harness runs are compromised and banner-flagged**; and the process lesson — *a measurable question was handed to an LLM, which fabricated the measurements twice; use code for counting, LLMs only for judgement.* Correct `mem:checkpoint/daab-mcp-harness-dasin-2026-07-16` (already partly retracted) and update `mem:backlog/ba033-slice2-readiness-path` with the FR-001 verdict.

---

## Self-Review

- **Coverage:** fabricated evidence contained → Task 1. Verified work landed + branch decision surfaced → Task 2. FR-001 answered without an LLM in the loop → Task 3. ✓
- **The trap this plan exists to avoid:** run 1's #1 recommendation ("fix `kg_graph_retrieve`") would send an engineer after a bug that does not exist. Task 1 Step 2 kills that specific instruction at its source; the "READ FIRST" block kills it here.
- **Type/contract consistency:** `kg_graph_retrieve` params match `internal/handler/graph_retrieve.go:49-55` verbatim (`result_k`, **not** `limit`; `include_snippet` opt-in). Transport mirrors `mcp_call.py`. Project ID is resolved by name everywhere — the hardcoded-UUID mistake already cost one wrong-project debugging detour this session.
- **Deliberately out of scope:** `kg_get_context` 404s, `kg_search_chunks` silent `limit` clamp, `kg_related_documents` centrality/IDF, typed edges, `aliases: []`, the numeral-vs-words OCR check, the contradiction layer. **All were reported by compromised runs** — several may be real, but **every one must be re-verified by direct measurement before it earns a plan.** Task 3's method is the template.
- **Risks:**
  - Task 3 measures **reach**, not **answer quality** — deliberately. Judging whether a `gr_only` snippet answers a question is a human step over the dumped output; folding that into the script would re-introduce exactly the failure this plan corrects.
  - **N=9 cannot settle BA-033 Slice 2.** Task 3 tests the *mechanism* (does hop-1 add reach, and on which query class), not the *scale* question. The heterogeneous/homogeneous split is designed to produce a claim that is testable at 145 documents; say so in the verdict.
  - A clean negative (`hop1_only_docs == 0`) is a **success** for this plan, not a failure to explain away.
