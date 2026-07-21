# Harness-Findings Fixes (silent-failure + contract hardening) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Fix the **real** defects the Dasin MCP consumer run exposed. All three are the same disease: **something fails or is misused, and nothing says so.** A whole audited financial statement fell out of the graph on a swallowed LLM error; a consumer concluded the flagship retrieval tool was broken because the API accepted parameters that do not exist; place/authority entities silently split.

**Architecture:** Three independent, surgical fixes. (1) `ingestion/pipeline/extract.py` — stop swallowing extraction-JSON parse failures; retry, then fail loud. (2) `internal/handler/graph_retrieve.go` — reject unknown request fields (`DisallowUnknownFields`). (3) `ingestion/pipeline/decompose.py` — extend `_LEGAL_FORMS` to place/authority abbreviations. No schema changes, no new features.

**Tech Stack:** Python 3.12 (`uv`, pytest, ruff line-length=100), Go (stdlib `net/http`, `encoding/json`, `make test`).

## ⚠️ READ FIRST — the harness's #1 finding was WRONG. Do not "fix" `kg_graph_retrieve`'s output.

`findings-dasin.md` recommends, as priority #1, fixing `kg_graph_retrieve` because it "returns no passage text", "silently ignores `limit`", and "discards the 1-hop expansion (`hop_count: 0` on every row)". **That diagnosis is false and was disproven by direct measurement.** The analyst used **parameter names that do not exist**, and the main session's "independent verification" reproduced the same symptom **using the same wrong parameters** — verifying a symptom, not a diagnosis.

**The API contract (`internal/handler/graph_retrieve.go:49-55`) is:** `query`, `project_id`, `result_k`, `seed_k`, `per_document_cap`, `mode`, `include_snippet`. **There is no `limit`.** Snippets are opt-in via `include_snippet` (built deliberately for token efficiency — `service/graph_retriever.go:100` `Snippet json.RawMessage`).

**Measured with correct parameters** (`{"query":"doanh thu thuần 2023 2024 2025","include_snippet":true,"result_k":20}`):
| | analyst's call (wrong params) | correct call |
|---|---|---|
| rows | 5 | **9** |
| snippet text | none | **9/9 rows** |
| `hop_count` values | `[0]` | **`[0, 1]` — expansion DOES reach the output** |
| distinct documents | — | **6** |

⟹ **`kg_graph_retrieve` works. FR-001 is NOT "untested because broken".** Q8's score of 2 in `findings-dasin.md` is an artefact of tool misuse and should be re-run before any FR-001 verdict. **The only real defect here is Task 2 below** — the endpoint silently accepted `limit`/`zzz_bogus`, which is *what produced the false diagnosis in the first place*.

## Global Constraints
- **Fail loud (AGENTS.md Rule 12)** is the theme. Every fix converts a silent failure into a visible one. Do not add a fix that logs at `debug` and continues.
- **Surgical (Rule 3):** touch only the three files named + their tests. Do **not** build typed edges (`alias_of`/`branch_of`/`issued_by`), `kg_corpus_map`, or the contradiction layer — those are **features**, separately decided, and the contradiction layer is explicitly gated on ingest quality (this plan).
- **Do not change `include_snippet`'s default.** Opt-in snippets are the deliberate token-efficiency design. Discoverability is handled by Task 2 (a 400 naming the valid fields), not by changing defaults.
- **Verify:** Python `cd ennam.kg.python && uv run pytest <file> -v`, lint `uv run ruff check src/ tests/`. Go `cd ennam.kg.go && make test && go build ./...`.
- Nested git: `git -C ennam.kg.python`, `git -C ennam.kg.go`.

## Evidence (measured 2026-07-16, project `Dasin` = `c47988fa-cb77-4367-94dc-36158956082b`)
Concept edges per document — **BCTC2023 is the only zero**:
```
BCTC KIEM TOAN 2023 | 0   ← orphaned
PLDL TANG VON       | 2
BCTC KIEM TOAN 2024 | 4
BCTC KIEM TOAN 2025 | 5
GCNDKKD L2 / L8     | 6 / 6
GPDT X2 / X3 / X1   | 7 / 7 / 12
```
Worker log, the smoking gun:
```
WARNING  ennam_kg.ingestion.pipeline.extract — extraction JSON parse failed, using empty result
INFO     decompose — concepts resolved: doc=BCTC KIEM TOAN 2023 DASIN-VND.pdf created=0 reused=0
```
⟹ the extraction LLM returned unparseable JSON, the pipeline substituted an **empty result**, and ingestion reported success. **11% of the corpus — a core audited financial statement — is invisible to every entity tool** (`kg_related_documents`, `kg_document_shared_entities`, `kg_get_neighbors`) and reachable only by chunk search. **This is non-deterministic** (LLM output): today BCTC2023, tomorrow any document.

Also confirmed working (do not touch): concept dedup — `concepts resolved: doc=GPDT X2 created=2 reused=5`; `kg_get_neighbors(ĐẠI TÂN)` bridges 8 documents in one call; `kg_related_documents` IDF ranking correctly surfaces the auditor (idf 1.50) over the ubiquitous target (idf 0.12).

## File Structure
- `src/ennam_kg/ingestion/pipeline/extract.py` (modify) — retry + fail loud on unparseable extraction JSON.
- `tests/ingestion/test_extract_failure.py` (create) — parse-failure behaviour.
- `internal/handler/graph_retrieve.go` (modify) — `DisallowUnknownFields`.
- `internal/handler/graph_retrieve_test.go` (modify/create) — unknown-field → 400.
- `src/ennam_kg/ingestion/pipeline/decompose.py` (modify) — extend `_LEGAL_FORMS`.
- `tests/ingestion/test_decompose_concepts.py` (modify) — place/authority variants.

---

## Task 1: Stop silently dropping a document's entities on extraction-JSON parse failure

**Files:** modify `src/ennam_kg/ingestion/pipeline/extract.py`; test `tests/ingestion/test_extract_failure.py` (create).

**Interfaces:**
- Read `extract.py` first and locate the `except` that logs `"extraction JSON parse failed, using empty result"`. Keep the existing function signature and return type **unchanged** — callers (`decompose.py` reads `extraction.entities`) must not change.
- Produces: on unparseable JSON → **retry once**; if the retry also fails → **raise** (not return empty), so `run_batch`'s existing per-document error handling records a failed document instead of a silently empty one.

- [ ] **Step 1: Read the current failure path.** `grep -n "JSON parse failed\|json.loads\|except" src/ennam_kg/ingestion/pipeline/extract.py` — find the swallow site, the LLM-call function it wraps, and what the caller does with the result. **Do not guess the shape; mirror what is there.**

- [ ] **Step 2: Write the failing test** — `tests/ingestion/test_extract_failure.py`:
```python
import pytest

# Import the extraction entry point + the AI-client seam you found in Step 1.
# Mirror the mocking style already used in tests/ingestion/ (read one first).


@pytest.mark.asyncio
async def test_unparseable_extraction_json_retries_then_raises():
    """Regression: BCTC2023 lost ALL entities because a bad LLM JSON response
    was swallowed into an empty result and ingestion reported success —
    11% of a corpus silently invisible to every entity tool."""
    calls = []

    async def _bad_llm(*args, **kwargs):
        calls.append(1)
        return "not json at all {{{"

    # monkeypatch the AI client seam with _bad_llm, then:
    with pytest.raises(Exception):
        await extract_entities(...)          # real name/args from Step 1
    assert len(calls) == 2, "must retry exactly once before failing"


@pytest.mark.asyncio
async def test_retry_succeeds_returns_entities():
    """A transient bad response must not lose the document."""
    responses = ["}}} broken", '{"entities": ["CÔNG TY TNHH ĐẠI TÂN"]}']

    async def _flaky_llm(*args, **kwargs):
        return responses.pop(0)

    # monkeypatch, then:
    result = await extract_entities(...)
    assert "CÔNG TY TNHH ĐẠI TÂN" in result.entities
```
> Fill the `...` from Step 1's real signature and mirror an existing test's mocking style (`tests/ingestion/test_decompose_concepts.py` has a `_FakeKG` pattern). Do not invent a new fixture style.

- [ ] **Step 3: Run → fail.** `cd ennam.kg.python && uv run pytest tests/ingestion/test_extract_failure.py -v`

- [ ] **Step 4: Implement.** At the swallow site: retry the LLM call **once** on parse failure (log the first failure at `WARNING` with the document title and a truncated response body — the current log names neither). If the retry also fails to parse, **raise** with the document title and the response prefix in the message. Do **not** return an empty result.

- [ ] **Step 5: Run → pass**, then the wider suite: `uv run pytest tests/ingestion/ -v` (existing decompose/canonical tests must stay green).

- [ ] **Step 6: Commit.**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/pipeline/extract.py tests/ingestion/test_extract_failure.py
git -C ennam.kg.python commit -m "fix(ingestion): retry then fail loud on unparseable extraction JSON instead of dropping all entities"
```

---

## Task 2: Reject unknown fields on `kg_graph_retrieve` (the defect that caused the false diagnosis)

**Files:** modify `internal/handler/graph_retrieve.go`; test `internal/handler/graph_retrieve_test.go`.

**Interfaces:**
- Valid fields stay exactly: `query`, `project_id`, `result_k`, `seed_k`, `per_document_cap`, `mode`, `include_snippet` (`graph_retrieve.go:49-55`). **No behaviour change for valid requests.**
- Produces: an unknown field (`limit`, `zzz_bogus`, `max_chunks`) → **400** with a message naming the field and listing the valid ones.

- [ ] **Step 1: Write the failing test** — in `internal/handler/graph_retrieve_test.go` (mirror the existing handler-test style in that package):
```go
func TestGraphRetrieve_RejectsUnknownField(t *testing.T) {
	// Regression: the endpoint silently accepted `limit` (which does not exist;
	// the real field is result_k). A consumer concluded the tool was broken and
	// filed a false "kg_graph_retrieve is broken" report. Unknown fields must 400.
	body := strings.NewReader(`{"query":"x","project_id":"p1","limit":60}`)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/graph-retrieve", body)
	w := httptest.NewRecorder()
	// ... construct the handler as the neighbouring tests do ...
	if w.Code != http.StatusBadRequest {
		t.Fatalf("unknown field must 400, got %d: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "limit") {
		t.Errorf("error must name the offending field, got: %s", w.Body.String())
	}
}

func TestGraphRetrieve_AcceptsValidFields(t *testing.T) {
	body := strings.NewReader(`{"query":"x","project_id":"p1","result_k":20,"include_snippet":true}`)
	// ... must NOT 400 ...
}
```
> Read the existing tests in `internal/handler/graph_retrieve_test.go` (or a sibling handler test) for the exact handler construction + route path. Mirror it.

- [ ] **Step 2: Run → fail.** `cd ennam.kg.go && go test ./internal/handler/ -run GraphRetrieve -v`
Expected: `TestGraphRetrieve_RejectsUnknownField` fails (currently 200/2xx — the unknown field is ignored).

- [ ] **Step 3: Implement.** In the request-decode block, replace `json.NewDecoder(r.Body).Decode(&req)` with a decoder that has `DisallowUnknownFields()` set, and on error return `errorResponse(w, http.StatusBadRequest, ...)` with a message naming the valid fields, e.g.:
```go
dec := json.NewDecoder(r.Body)
dec.DisallowUnknownFields()
if err := dec.Decode(&req); err != nil {
	errorResponse(w, http.StatusBadRequest, fmt.Sprintf(
		"invalid request: %v (valid fields: query, project_id, result_k, seed_k, per_document_cap, mode, include_snippet)", err))
	return
}
```
> Read the current decode + error-response helper in this file and match it; do not introduce a second error style.

- [ ] **Step 4: Run → pass** + `go build ./... && make test`.

- [ ] **Step 5: Commit.**
```bash
git -C ennam.kg.go add internal/handler/graph_retrieve.go internal/handler/graph_retrieve_test.go
git -C ennam.kg.go commit -m "fix(retrieve): reject unknown request fields on graph-retrieve instead of silently ignoring them"
```

> **Follow-up candidate (not this plan):** the same `DisallowUnknownFields` gap likely exists on other handlers. Fixing it fleet-wide is a separate, larger change — record it, do not scope-creep here.

---

## Task 3: Extend concept dedup to place / authority abbreviations

**Files:** modify `src/ennam_kg/ingestion/pipeline/decompose.py` (`_LEGAL_FORMS`); test `tests/ingestion/test_decompose_concepts.py`.

**Interfaces:** `_resolve_concept_key(name) -> str` unchanged in signature; only the abbreviation map grows. `_LEGAL_FORMS` entries are applied **after** `fold_name` (which lowercases + strips diacritics), so **the map's keys must be in folded form**.

**Evidence:** the concept-dedup fix covers company names only. Still split in Dasin: `KCX Tân Thuận` / `Khu chế xuất Tân Thuận`; `Ban Quản lý các Khu Chế Xuất và Công Nghiệp TP.HCM` / `Ban Quản lý các Khu chế xuất và Công nghiệp Thành phố Hồ Chí Minh`. Splits silently corrupt `kg_related_documents` IDF (a split entity inflates rarity on both halves and understates connectivity).

- [ ] **Step 1: Confirm the folded forms first.** Do not guess the strings:
```bash
cd ennam.kg.python && uv run python -c "
from ennam_kg.resolution.name_fold import fold_name
for s in ['KCX Tân Thuận','Khu chế xuất Tân Thuận',
          'Ban Quản lý các Khu Chế Xuất và Công Nghiệp TP.HCM',
          'Ban Quản lý các Khu chế xuất và Công nghiệp Thành phố Hồ Chí Minh',
          'KCN Phú An Thạnh','Khu công nghiệp Phú An Thạnh']:
    print(repr(fold_name(s)))"
```
Use the **actual** output to write the map in Step 3.

- [ ] **Step 2: Write the failing test** — append to `tests/ingestion/test_decompose_concepts.py`:
```python
def test_place_and_authority_abbreviations_collapse():
    assert _resolve_concept_key("KCX Tân Thuận") == _resolve_concept_key("Khu chế xuất Tân Thuận")
    assert _resolve_concept_key("KCN Phú An Thạnh") == _resolve_concept_key("Khu công nghiệp Phú An Thạnh")
    assert _resolve_concept_key(
        "Ban Quản lý các Khu Chế Xuất và Công Nghiệp TP.HCM"
    ) == _resolve_concept_key(
        "Ban Quản lý các Khu chế xuất và Công nghiệp Thành phố Hồ Chí Minh"
    )


def test_distinct_places_still_separate():
    # Guard against over-merging: different zones must NOT collapse.
    assert _resolve_concept_key("KCX Tân Thuận") != _resolve_concept_key("KCN Phú An Thạnh")
```

- [ ] **Step 3: Run → fail**, then extend `_LEGAL_FORMS` using the folded strings from Step 1 — e.g. (verify against real output):
```python
_LEGAL_FORMS: tuple[tuple[str, str], ...] = (
    ("trach nhiem huu han", "tnhh"),
    ("cong ty co phan", "ctcp"),
    # Places / authorities — Dasin corpus split these into duplicate nodes.
    ("khu che xuat", "kcx"),
    ("khu cong nghiep", "kcn"),
    ("thanh pho ho chi minh", "tphcm"),
    ("tp hcm", "tphcm"),
    ("tp.hcm", "tphcm"),
)
```
> **Order matters** — apply longer forms before shorter ones so `thanh pho ho chi minh` is not partially rewritten. Verify with the Step 2 tests, and re-run the existing `test_fold_key_keeps_distinct_entities_apart` to confirm no over-merging.

- [ ] **Step 4: Run → pass.** `uv run pytest tests/ingestion/ -v` (whole directory — the existing concept tests must stay green).

- [ ] **Step 5: Commit.**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/pipeline/decompose.py tests/ingestion/test_decompose_concepts.py
git -C ennam.kg.python commit -m "fix(ingestion): dedup place and authority abbreviations, not just company legal forms"
```

---

## Task 4: Rebuild, re-ingest, and re-measure (operational)

**Files:** none. Requires the Docker stack (`daab-worker`, `daab-server` :8082, `daab-postgres` :5433).

**Baselines (Dasin, 2026-07-16):** BCTC2023 concept edges **0**; concepts **26** with `KCX Tân Thuận`/`Khu chế xuất Tân Thuận` and two HEPZA nodes still split.

- [ ] **Step 1: Rebuild.** `cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace && docker compose up -d --build daab-worker daab-server`

- [ ] **Step 2: Re-ingest.** **Delete** the `Dasin` project in the dashboard (`localhost:3500/projects`), re-create, connect AAAA + Sync (or Local Upload `doc_pdf_test/project_3`).
> Re-syncing an existing project is a **no-op** (`aaaa_synced_document` dedups on `(document_id, content_hash)`; the bytes are unchanged). Deleting cascades the sync-state rows.
> ⚠️ **The project UUID changes on every re-ingest.** Always resolve it as `(SELECT id FROM projects WHERE name='Dasin')` — never hardcode. (A stale hardcoded ID already cost one wrong-project debugging detour.)

- [ ] **Step 3: Run the FR-001 linker — REQUIRED after every ingest, it is not automatic.**
```bash
PID=$(docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -c "SELECT id FROM projects WHERE name='Dasin';" | tr -d '\r')
curl -s -X POST "http://localhost:8082/api/v1/internal/graphrag/link" \
  -H "Authorization: Bearer $KG_API_KEY" -H "Content-Type: application/json" \
  -d "{\"project_id\":\"$PID\"}"
```
Expected: `edges_upserted` in the hundreds. Without this, `similar_to` stays near-zero and `kg_graph_retrieve` has no substrate (last run: 5 edges → 396 after linking).

- [ ] **Step 4: Measure — no orphaned documents (Task 1).**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT left(d.title,32),
 (SELECT count(*) FROM knowledge_edges e WHERE e.source_id=d.id AND e.edge_type='mentions') AS concept_edges
FROM knowledge_nodes d
WHERE d.project_id=(SELECT id FROM projects WHERE name='Dasin') AND d.node_type='document'
ORDER BY 2;"
```
Expected: **every document ≥ 1** — in particular `BCTC KIEM TOAN 2023` > 0 (was 0). If a document still shows 0, the extraction now **raises** instead of silently emptying, so check the worker log for the loud failure and the doc's ingest status — a visible failure is the intended outcome, an invisible one is not.

- [ ] **Step 5: Measure — place/authority collapse (Task 3).**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT title FROM latest_knowledge_nodes
WHERE project_id=(SELECT id FROM projects WHERE name='Dasin') AND node_type='concept'
  AND (title ILIKE '%Tân Thuận%' OR title ILIKE '%Khu Chế Xuất%' OR title ILIKE '%Phú An Thạnh%')
ORDER BY 1;"
```
Expected: **one** node for Tân Thuận EPZ, **one** for the HEPZA authority, **one** for Phú An Thạnh IP (each was 2+). Total concepts should drop below 26.

- [ ] **Step 6: Verify Task 2.**
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8082/api/v1/graph-retrieve \
  -H "Authorization: Bearer $KG_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"x","project_id":"'"$PID"'","limit":60}'     # expect 400
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8082/api/v1/graph-retrieve \
  -H "Authorization: Bearer $KG_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"doanh thu","project_id":"'"$PID"'","result_k":20,"include_snippet":true}'   # expect 200
```
> Read the real route path from `graph_retrieve.go`'s route registration if the above 404s.

- [ ] **Step 7: Re-run the harness with CORRECT parameters and settle FR-001.** Re-run `other_projects/daab-sim-consumer/questions-dasin.md` (persona + rubric in that project's `CLAUDE.md`; HTTP-MCP via scratchpad `mcp_call.py`, `X-KG-Project-Id` header). **Tell the analyst the real parameter names** (`result_k`, `seed_k`, `include_snippet` — there is no `limit`). Compare against `findings-dasin.md`: Q8/Q9/Q10 should improve, and this produces **the first honest FR-001 verdict**. Write `findings-dasin-run2.md`.

- [ ] **Step 8: Checkpoint** — `mcp__serena__write_memory("checkpoint/harness-findings-fixes-<YYYY-MM-DD>", …)` with before/after; correct `mem:checkpoint/daab-mcp-harness-dasin-2026-07-16`, whose finding #1 (`kg_graph_retrieve` is broken) is **wrong** and must be retracted; update `mem:backlog/ba033-slice2-readiness-path` with the FR-001 verdict.

---

## Self-Review

- **Findings coverage:** BCTC2023 silent orphan (root cause found in the worker log: `extraction JSON parse failed, using empty result`) → Task 1. Unknown-field acceptance, the defect that *caused* the false "graph_retrieve is broken" report → Task 2. Place/authority concept splits corrupting IDF → Task 3. Operational proof → Task 4. ✓
- **Deliberately NOT in scope, with reasons:**
  - **"Fix `kg_graph_retrieve`'s output stage"** — **the finding is false**; disproven by measurement with correct params (9 rows, 9/9 snippets, `hop_count [0,1]`, 6 documents). Building it would be work against a bug that does not exist.
  - **Typed edges (`alias_of`/`branch_of`/`issued_by`), `kg_corpus_map`, contradiction/reconciliation layer** — **features, not fixes**. The contradiction layer is explicitly gated on ingest quality (this plan) — 2 of 5 "contradictions" the analyst found were OCR artefacts, so shipping it on today's data would emit more false positives than true ones.
  - **Numeral-vs-Vietnamese-words cross-check** (would catch the PLDL `10.146.508.403` vs "một trăm tỷ" **10× OCR error**) — genuinely valuable and evidence-backed, but it is a **new OCR validation feature** with real design questions (where does it run? what does it do on mismatch — reject, flag, or auto-correct from the words?). It deserves its own brainstorm + plan, not a bullet here. **Recorded as the top follow-up.**
  - **`kg_search` recall miss** on `Ban Quản lý Khu kinh tế tỉnh Long An` — **undiagnosed**. No root cause ⇒ no fix (systematic-debugging's Iron Law). Needs its own investigation.
  - **`kg_related_documents` returns IDs without filenames**, and `DisallowUnknownFields` is likely missing fleet-wide — both real, both follow-ups.
- **Type consistency:** Task 1 keeps the extraction function's signature/return type (callers read `extraction.entities` in `decompose.py`). Task 2 changes only the decoder, not the request struct (`graph_retrieve.go:49-55`) or any valid-request behaviour. Task 3 changes only `_LEGAL_FORMS` contents; `_resolve_concept_key` keeps `(str) -> str`.
- **Read-before-write points (named, not hand-waved):** `extract.py`'s swallow site + AI-client seam + caller contract (Task 1 Step 1); the existing handler-test construction + error-response helper (Task 2 Steps 1/3); the **real** folded output of `fold_name` (Task 3 Step 1). Each says which file to mirror.
- **Risks:**
  - Task 1 makes ingestion **fail** where it previously succeeded-with-empty. That is the point (Rule 12), but a flaky LLM will now surface as visible document failures — the retry mitigates transients. If the failure rate proves high, the answer is a better extraction prompt/parser, **not** re-swallowing the error.
  - Task 3's abbreviation map is a **blunt string rewrite**. `_MANGLED`-style over-merging is guarded by `test_distinct_places_still_separate` and the existing branch/parent test, but the map must stay small and corpus-driven — not a general Vietnamese abbreviation dictionary.
  - Task 2 could break an existing caller that sends extra fields. Grep for callers of the endpoint (`kg-bridge`, the Next dashboard) before merging; a 400 on a previously-tolerated field is a breaking change if anyone relies on it.
