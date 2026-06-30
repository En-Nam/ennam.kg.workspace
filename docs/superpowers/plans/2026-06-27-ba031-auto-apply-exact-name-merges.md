# BA-031 — Auto-Apply Exact-Name Merges (collapse casing/diacritic entity duplicates) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).
> **Self-contained** — viết để execute ở session khác; đọc kỹ Context + Verified facts trước.

**Goal:** Auto-apply CHỈ band **exact normalized-name** của merge_suggestions (lossless) để gộp entity trùng casing/dấu/separator/honorific (vd "Ban Quản lý Khu kinh tế Trà Vinh" ×5 + "BAN QUẢN LÝ...") → cross-doc graph gọn → semantic search chính xác/ổn định (mục tiêu BA-033). **Giữ band fuzzy (CE/LLM) ở shadow** (data-gate BA-031 không đổi).

**Architecture:** pass2 (Python, shadow) đã ghi `merge_suggestions` cho band exact-name với `reason='exact normalized name match'`, `merge_confidence=0.99`, `decision='suggested'` — nhưng KHÔNG apply (shadow). Fix = thêm đường Go apply **selective** chỉ áp suggestion exact-name (reuse máy merge sẵn có), **KHÔNG gated bởi global `apply_mode`** (vì lossless), tách hẳn band fuzzy.

**Tech Stack:** Go (`internal/service/apply_suggestions.go`, `internal/handler/apply_suggestions.go`, `internal/store`), PostgreSQL. Trigger: Python worker gọi endpoint sau pass2.

## Context (vì sao fix này, đã verify)
- Seed 10 doc thật → entity trùng nặng: cùng thực thể thành 3-5 node (casing/dấu/EN — EN đã fix; **casing/dấu còn**). → phân mảnh cross-doc graph → retrieval kém.
- **`rules.py` (verified):** `action="merge"` GIỜ chỉ từ **exact normalized-name** (`_normalize` = NFC+lower+collapse `[\s\-_.]`+strip honorific). High-sim auto-merge **đã GỠ** (G6, 2026-06-23) → không còn band "merge" nguy hiểm; mọi ca mờ → `defer`. ⇒ **rule-merge band = lossless**.
- **pass2 shadow** (`run_pass2_shadow`, FR-NEW-6) **chỉ ghi** merge_suggestions, không apply. → casing-merge nằm chờ.
- **Apply hiện tại** gated **fail-closed** trên global `apply_mode != "apply"` (`apply_suggestions.go:89`) → áp TẤT CẢ suggested (cả fuzzy) khi bật. Bật global = rủi ro band fuzzy + cần data-gate. → **Không bật global**; thêm đường selective lossless.

## Global Constraints
- **CHỈ apply `reason='exact normalized name match'`** (literal — discriminator chính xác band lossless). KHÔNG đụng suggestion CE/LLM (fuzzy).
- **KHÔNG gated bởi global `apply_mode`** (lossless không cần data-gate) — nhưng có **config flag riêng** `resolution.auto_apply_exact_name` (default `true`) để tắt được.
- **Bypass degree-gate** cho band exact-name (lossless → đúng bất kể degree; degree-gate là cho band rủi ro).
- Reuse `ApplySuggestionsService.processSuggestion` (merge machinery + reversible un-merge sẵn có) — KHÔNG viết merge mới.
- Idempotent: chỉ xử `decision='suggested'`; sau merge → `decision='applied'`.
- Test: Go `make test` (mock store). Nested git `git -C ennam.kg.go`.

## Verified facts (2026-06-27)
- `merge_suggestions` (migration 000064): `node_a_id, node_b_id, embedding_similarity, merge_confidence, proposed_canonical_id, resolution_model, reason, degree_max, decision('suggested'|'applied'|'rejected'|'needs_review')`; index `(project_id, decision)`.
- pass2 ghi: `reason` từ RuleResult; exact-name = `"exact normalized name match"`, `merge_confidence=0.99` (`rules.py EXACT_NAME_CONFIDENCE`).
- Apply handler: `POST /api/v1/internal/resolution/apply` (`apply_suggestions.go:48`), gate `h.resolution.ApplyMode != "apply"` (L89).
- Apply service: `ApplySuggestionsService.Apply(ctx, projectID, degreeThreshold)` (L84) → loop suggested → `processSuggestion` (L107) merge w/ degree gate.

---

## Task 1: Service — `ApplyExactNameMerges` (selective, lossless)

**Files:** Modify `internal/service/apply_suggestions.go`; store list-by-reason. Test: `internal/service/apply_suggestions_test.go`.

**Interfaces:**
- Produces: `(*ApplySuggestionsService) ApplyExactNameMerges(ctx context.Context, projectID string) (ApplyResult, error)` — áp chỉ `decision='suggested' AND reason='exact normalized name match'`, bypass degree-gate.
- Store: `ListExactNameSuggestions(ctx, projectID string) ([]MergeSuggestion, error)` — `WHERE project_id=$1 AND decision='suggested' AND reason='exact normalized name match'`.

- [ ] **Step 1: Read first** — `processSuggestion` (apply_suggestions.go:107) signature + cách nó áp degree-gate (param `degreeThreshold`). Xác định cách **bypass degree-gate** cho exact-name: hoặc gọi `processSuggestion` với `degreeThreshold` đủ lớn để luôn-qua, hoặc tách nhánh skip degree. Đọc để chọn cách sạch (đừng đổi hành vi `Apply` cũ).

- [ ] **Step 2: Write failing test**
```go
func TestApplyExactNameMerges_OnlyExactBand(t *testing.T) {
    // fake store: 3 suggestions (decision='suggested'):
    //   s1 reason="exact normalized name match"  → PHẢI merge
    //   s2 reason="LLM verified: same entity"     → KHÔNG đụng
    //   s3 reason="exact normalized name match", decision='applied' → bỏ qua (đã applied)
    svc := NewApplySuggestionsService(fakeMerger, fakeStore, /*resolution*/ cfgShadow, ...)
    res, err := svc.ApplyExactNameMerges(context.Background(), "p1")
    if err != nil { t.Fatal(err) }
    if res.Applied != 1 { t.Errorf("want 1 applied (exact-name only), got %d", res.Applied) }
    if fakeMerger.merged(s2.NodeAID, s2.NodeBID) { t.Error("fuzzy suggestion must NOT be applied") }
}

func TestApplyExactNameMerges_NotGatedByApplyMode(t *testing.T) {
    // resolution.ApplyMode = "shadow" → ApplyExactNameMerges VẪN chạy (lossless path)
    svc := NewApplySuggestionsService(fakeMerger, fakeStore, cfgShadow, ...)
    res, _ := svc.ApplyExactNameMerges(context.Background(), "p1")
    if res.Applied == 0 { t.Error("exact-name apply must run even in shadow mode") }
}
```

- [ ] **Step 3: Run → fail.** `cd ennam.kg.go && go test ./internal/service/ -run ApplyExactNameMerges -v`

- [ ] **Step 4: Implement** — store `ListExactNameSuggestions` + service:
```go
func (s *ApplySuggestionsService) ApplyExactNameMerges(ctx context.Context, projectID string) (ApplyResult, error) {
    sugg, err := s.store.ListExactNameSuggestions(ctx, projectID)
    if err != nil {
        return ApplyResult{}, fmt.Errorf("list exact-name suggestions: %w", err)
    }
    var res ApplyResult
    for _, sg := range sugg {
        // Lossless band → bypass degree gate (exact normalized name = same real entity).
        if err := s.processSuggestion(ctx, sg, /*bypassDegreeGate*/ true); err != nil {
            s.logger.Warn("exact-name merge failed", "pair", sg.ID, "error", err)
            res.Failed++
            continue
        }
        res.Applied++
    }
    return res, nil
}
```
> Nếu `processSuggestion` không có cờ bypass → thêm param `bypassDegreeGate bool` (default false ở caller `Apply` cũ để KHÔNG đổi hành vi), true ở đây. Hoặc tách helper `mergePair`. Đọc Step 1 để chọn ít-đụng nhất. KHÔNG gated bởi `apply_mode` ở method này.

- [ ] **Step 5: Run → pass.** `go test ./internal/service/ -run ApplyExactNameMerges -race -v && go build ./...`

- [ ] **Step 6: Commit**
```bash
git -C ennam.kg.go add internal/service/apply_suggestions.go internal/store/ internal/service/apply_suggestions_test.go
git -C ennam.kg.go commit -m "feat(ba031): ApplyExactNameMerges — selective lossless apply of exact-name dups"
```

---

## Task 2: Endpoint + config flag

**Files:** Modify `internal/handler/apply_suggestions.go` (new route), `internal/config` (flag), `cmd/kg-server/main.go`. Test: handler test.

**Interfaces:**
- `POST /api/v1/internal/resolution/apply-exact-name` body `{"project_id": "..."}` → `ApplyExactNameMerges`. **KHÔNG** gate `apply_mode`; gate bằng flag `resolution.auto_apply_exact_name` (default true).
- Config: `ResolutionConfig.AutoApplyExactName bool` (env `KG_RESOLUTION_AUTO_APPLY_EXACT_NAME`, default true).

- [ ] **Step 1: Config flag** — thêm `AutoApplyExactName bool` vào `ResolutionConfig` (default true; env parse). Đọc `internal/config` ResolutionConfig hiện tại để khớp pattern.

- [ ] **Step 2: Write failing test** (`apply_suggestions_test.go` handler):
```go
func TestHandleApplyExactName_RunsInShadow(t *testing.T) {
    h := NewApplySuggestionsHandler(fakeApplier, config.ResolutionConfig{ApplyMode: "shadow", AutoApplyExactName: true})
    rr := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/resolution/apply-exact-name", strings.NewReader(`{"project_id":"p1"}`))
    h.HandleApplyExactName(rr, req)
    if rr.Code != http.StatusOK { t.Errorf("want 200 (runs in shadow), got %d", rr.Code) }
    if !fakeApplier.exactCalled { t.Error("ApplyExactNameMerges not invoked") }
}
func TestHandleApplyExactName_DisabledByFlag(t *testing.T) {
    h := NewApplySuggestionsHandler(fakeApplier, config.ResolutionConfig{AutoApplyExactName: false})
    rr := httptest.NewRecorder()
    h.HandleApplyExactName(rr, httptest.NewRequest(http.MethodPost, "/api/v1/internal/resolution/apply-exact-name", strings.NewReader(`{"project_id":"p1"}`)))
    if rr.Code != http.StatusServiceUnavailable { t.Errorf("want 503 when flag off, got %d", rr.Code) }
}
```
> `Applier` interface (apply_suggestions.go) cần thêm `ApplyExactNameMerges(ctx, projectID) (ApplyResult, error)` — thêm vào interface + fake.

- [ ] **Step 3: Implement handler** — `HandleApplyExactName`: nếu `!h.resolution.AutoApplyExactName` → 503; else parse project_id → `h.applier.ApplyExactNameMerges(ctx, pid)` → 200 + result. Register route. Wire main.go (đọc chỗ construct handler).

- [ ] **Step 4: Run + build.** `go test ./internal/handler/ -run ApplyExactName -race -v && go build ./...`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/handler/apply_suggestions.go internal/config/ cmd/kg-server/main.go internal/handler/apply_suggestions_test.go
git -C ennam.kg.go commit -m "feat(ba031): apply-exact-name endpoint + auto_apply_exact_name flag"
```

---

## Task 3: Trigger sau pass2 (worker)

**Files:** Modify `ennam.kg.python/src/ennam_kg/worker.py` (sau `run_pass2_shadow`). Test: `tests/` (mock httpx).

**Interfaces:** Worker gọi `POST /api/v1/internal/resolution/apply-exact-name` (qua KGClient hoặc httpx-to-Go) per project sau khi pass2 ghi suggestions.

- [ ] **Step 1: Read first** — chỗ `run_pass2_shadow` được gọi trong worker (sau extraction batch). Quyết gọi apply-exact-name 1 lần/project sau khi pass2 xong (không per-chunk — gọi cuối batch).

- [ ] **Step 2: Write failing test** — sau pass2 trong batch, worker gọi apply-exact-name đúng project; lỗi apply = non-fatal (log, không chặn).

- [ ] **Step 3: Implement** — sau `run_pass2_shadow(...)`:
```python
try:
    await kg_client.post("/api/v1/internal/resolution/apply-exact-name",
                         json={"project_id": project_id})
except Exception as exc:
    logger.warning("apply-exact-name failed (non-fatal): %s", exc)
```
> Dùng đúng KGClient method/httpx pattern sẵn có (đọc kg_client). Non-fatal.

- [ ] **Step 4: Run + commit**
```bash
git -C ennam.kg.python add src/ennam_kg/worker.py tests/
git -C ennam.kg.python commit -m "feat(ba031): worker triggers apply-exact-name after pass2"
```

---

## Task 4: Backfill corpus hiện tại + verify (E2E)

**Files:** none (vận hành). Stack live.

- [ ] **Step 1: Rebuild + apply cho project corpus đang có dup**
```bash
docker compose up -d --build kg-server worker
curl -s -X POST http://localhost:8080/api/v1/internal/resolution/apply-exact-name \
  -H "Authorization: Bearer $KG_API_KEY" -H "Content-Type: application/json" \
  -d '{"project_id":"<corpus-project-id>"}' | python3 -m json.tool
```
Expected: `applied > 0` (gộp các casing dup hiện tại).

- [ ] **Step 2: Verify dup giảm** (SQL):
```sql
-- trước/sau: đếm node concept trùng theo normalized name
select lower(title), count(*) from knowledge_nodes
 where node_type='concept' group by lower(title) having count(*)>1 order by count(*) desc limit 20;
```
Expected: "ban quản lý khu kinh tế trà vinh" còn **1 node** (trước ×5+); fuzzy KHÁC nhau KHÔNG bị gộp nhầm.

- [ ] **Step 3: Verify cross-doc mạnh hơn** — entity canonical giờ nối nhiều doc hơn (refs tăng):
```sql
select n.title, count(distinct e.source_id) refs from knowledge_edges e
 join knowledge_nodes n on n.id=e.target_id where n.node_type='concept'
 group by n.id,n.title having count(distinct e.source_id)>=2 order by refs desc limit 10;
```
Expected: entity chính (Hàm Giang, Định An, Trà Vinh) refs cao hơn (ít phân mảnh).

- [ ] **Step 4: Verify fuzzy KHÔNG bị đụng** — suggestion CE/LLM vẫn `decision='suggested'`:
```sql
select decision, count(*) from merge_suggestions
 where reason <> 'exact normalized name match' group by decision;
```
Expected: fuzzy suggestions vẫn 'suggested' (shadow giữ nguyên).

- [ ] **Step 5: Checkpoint** (Serena) — kết quả backfill + dup giảm.

---

## Self-Review (đã chạy)
- **Scope:** chỉ band `reason='exact normalized name match'` (lossless, verified rule-merge band duy nhất sau khi high-sim bị gỡ). Fuzzy CE/LLM KHÔNG đụng → data-gate BA-031 nguyên vẹn. ✓
- **An toàn:** lossless (normalize giống hệt) → 0 false-merge; bypass degree-gate hợp lý (lossless); reuse processSuggestion (un-merge reversible). ✓
- **Không gated apply_mode** (đúng — lossless không cần data-gate) nhưng có flag tắt riêng. ✓
- **Type consistency:** `ApplyExactNameMerges(ctx,projectID)→ApplyResult` (Task1) = Applier interface (Task2) = worker call (Task3). reason literal "exact normalized name match" khớp rules.py + pass2. ✓

## Open dependencies (execute-time)
- `processSuggestion` degree-gate bypass cơ chế (Task 1 Step 1) — đọc trước; thêm param `bypassDegreeGate` mặc định false cho `Apply` cũ.
- `ResolutionConfig` shape + env parse (Task 2) — khớp pattern config hiện tại.
- `Applier` interface — thêm method + fake.
- KGClient/httpx-to-Go method trong worker (Task 3) — dùng pattern sẵn có.
- `<corpus-project-id>` (Task 4) — project chứa 10 doc đã seed.
- ⚠️ Nếu sau muốn gộp fuzzy (CE/LLM) → đó là quyết định riêng + **cần data-gate BA-031** (precision/recall trên VI labeled set) — KHÔNG thuộc plan này.
