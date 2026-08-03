# Plan: Playbook management layer — AI đề xuất, người duyệt, tự phát hiện drift

**Ngày:** 2026-08-03 · **Implement:** 2026-08-04
**Tiền đề:** phase 1+2 đã ship trên `task/mcp-write-datasource` (describe/insert/playbook engine + `create_order` chạy atomic, rollback verified). Spec gốc: `docs/mcp-write-datasource-spec.md` §5.2–§5.3 + backlog `mcp-write-phase3-followups`.

**Mục tiêu lớp này:** khép kín vòng đời playbook — hiện tại seed/approve chỉ làm được bằng SQL tay; chưa gì đánh dấu `stale` khi schema đổi; chưa có AI đề xuất. Sau phase 3: *connect datasource → bấm "Propose" → duyệt draft trên dashboard → LAAM dùng được ngay; schema đổi thì playbook tự khóa chờ review.*

---

## Task 1 — Playbook CRUD + approve API (Go, ~nửa ngày)

Endpoints mới (đều trên `SourceWriteHandler`, project-role như hiện tại trừ khi ghi khác):

| Endpoint | Role | Ghi chú |
|---|---|---|
| `POST /api/v1/data-sources/{id}/playbooks` | developer | Tạo **draft**. Body: `{name, description, definition}`. Validate khi tạo: definition parse được, mọi `insert:` table + cột trong `values` tồn tại trong schema metadata (tái dùng `buildTableDescription`), template hợp lệ (chạy `expandPlaybook` với input giả từ spec → bắt lỗi template sớm). Fail → 400 nêu đúng chỗ. |
| `GET /api/v1/data-sources/{id}/playbooks/{name}` | developer | Xem 1 playbook (mọi status) + definition. |
| `GET /api/v1/data-sources/{id}/playbooks?all=true` | developer | List mọi status (hiện chỉ approved). |
| `POST .../playbooks/{name}/approve` | **admin** | draft/stale → approved (stale phải re-approve bằng người, không auto). Ghi `approved_by`, bump `version` nếu definition đổi từ lần approve trước. |
| `POST .../playbooks/{name}/disable` | admin | → disabled. |
| `PATCH .../playbooks/{name}` | developer | Sửa definition → status tự về **draft** (mọi sửa đổi mất hiệu lực approve). |
| `DELETE .../playbooks/{name}` | admin | Chỉ khi chưa từng execute thành công (check audit) — nếu có lịch sử thì disable thay vì xoá. |

- Migration 000085: thêm `approved_by TEXT`, `approved_at TIMESTAMPTZ` vào `write_playbooks`.
- **KHÔNG expose CRUD/approve qua MCP bridge** — quản trị là việc của người/dashboard; LAAM chỉ cần list-approved + execute (đã có). Đây là quyết định, ghi comment trong code.
- Audit: approve/disable ghi vào `source_write_audit` (operation `playbook_approve:<name>` …) để có vết ai duyệt.

**Success criteria:** tạo draft qua API với definition lỗi cột → 400 nêu cột; approve bằng key developer → 403; admin approve → LAAM list thấy ngay; sửa definition → về draft và `kg_execute_playbook` trả 403 "not approved".

## Task 2 — Stale-marking khi sync-schema (Go, ~nửa ngày) — BẮT BUỘC theo spec §5.3

- Hook vào cuối `SchemaSyncService` (sau khi metadata mới ghi xong): với datasource đó, load mọi playbook `approved` + `draft`, chạy validation như Task 1 (bảng/cột/kiểu còn tồn tại?).
  - Lệch → `status='stale'`, `status_reason` nêu cụ thể ("column customers.state dropped").
  - Hết lệch nhưng đang stale → **GIỮ stale** (người phải re-approve — schema quay lại không có nghĩa semantics còn đúng).
- `kg_execute_playbook` với playbook stale đã trả 409 kèm reason (có sẵn) — không cần sửa engine.
- Log WARNING mỗi lần đánh stale (Rule 12).

**Success criteria (test tích hợp trên pharmacy_demo):** `ALTER TABLE payments DROP COLUMN status` (bản copy/tx test) → sync-schema → `create_order` thành stale với reason nêu `payments.status` → execute trả 409 → restore cột + re-approve → chạy lại được.

## Task 3 — AI đề xuất playbook (Go deterministic + Python LLM, ~1 ngày)

Chia đúng Rule 5 — *code cho phần suy ra được từ cấu trúc, LLM chỉ cho phần ngữ nghĩa*:

**3a. Phân loại deterministic (Go, không LLM)** — `service/playbook_proposer.go`:
- Từ schema tree: đếm FK vào/ra từng bảng →
  - `entity` (nhiều FK vào, ít ra) → candidate `create_<singular>` (insert đơn, input = mọi cột non-default)
  - `header-detail` (B có FK về A, tên `A_items|A_lines|A_details`) → candidate composite
  - `event/ledger` (FK + cột timestamp + cột lượng signed) → KHÔNG đứng riêng, đánh dấu là side-effect candidate
- Kết quả: danh sách candidate + evidence (FK nào, naming nào) — thuần cấu trúc, test được bằng mock tree.

**3b. Suy side-effect + hoàn thiện bằng LLM (Python worker, message `propose_playbooks`):**
- Go endpoint `POST /data-sources/{id}/playbooks/propose` → queue message (pattern `generate_kg` sẵn có) → worker:
  1. Lấy candidates (3a) + schema + **mẫu dữ liệu pattern** qua đường đọc sẵn có (ví dụ: `reference_id` của ledger khớp prefix id bảng nào, dấu của cột lượng tương quan gì) — chỉ SELECT, dùng executor read-only.
  2. LLM (BytePlus, plumbing BA-031 sẵn) compose definition JSON hoàn chỉnh (steps + template) + description + confidence + evidence.
  3. Ghi về Go qua `POST .../playbooks` (Task 1) với status **draft**, `created_by='ai-proposer'`, evidence trong description.
- **Không bao giờ auto-approve.** Confidence < ngưỡng thì vẫn tạo draft nhưng gắn nhãn low-confidence.
- Job tracking qua `sync_jobs` (job_type mới `playbook_proposal`) để dashboard poll.

**Success criteria:** chạy propose trên pharmacy_demo → ≥4 draft đúng phân loại (create_customer, create_employee, add_product đơn; create_order composite có bước inventory_movements với `$neg`); tất cả draft; definition của create_order đề xuất phải pass validation Task 1.

## Task 4 — Dashboard UI (ennam.kg.next, ~1 ngày)

Trang datasource detail thêm tab **Playbooks**:
- Bảng: name, version, status badge (draft xám / approved xanh / stale đỏ + reason / disabled), created_by (ai-proposer vs người), approved_by.
- Xem definition (JSON viewer, diff với version trước nếu có).
- Nút Approve/Disable (admin), Propose playbooks (trigger 3b + poll job).
- Cùng chỗ: toggle `allow_writes` + editor `write_tables_whitelist` (hiện chỉnh bằng SQL — đưa lên UI, PATCH data-sources đã có).
- BFF proxy pattern như các trang hiện có; TanStack Query.

**Success criteria:** vòng đầy đủ không đụng SQL: propose → review draft trên UI → approve → hỏi LAAM "tạo đơn hàng…" chạy được; drop cột → badge stale đỏ hiện đúng reason.

## Task 5 (nếu còn thời gian) — MSSQL writes

`buildInsertSQL` dialect param (`@p1` + `sql.Named`), write connection sqlserver, bỏ reject. Test cần MSSQL container — có thể defer tiếp.

## Thứ tự & phụ thuộc

```
Task 1 (CRUD) ──┬─→ Task 2 (stale)      [1,2 song song được sau khi 1 xong validation helper]
                └─→ Task 3 (proposer ghi draft qua API Task 1)
Task 4 (UI) phụ thuộc 1+2+3 (API surface)
```

Branch: tiếp tục `task/mcp-write-datasource` hoặc branch mới `task/playbook-management` off nó (đề xuất: branch mới, giữ PR hiện tại reviewable). TDD như 2 phase trước; checkpoint Serena cuối mỗi task.

## Quyết định đã chốt trong plan (theo spec §8 + thực tế phase 1–2)
- CRUD/approve KHÔNG qua MCP; admin mới approve; stale không tự phục hồi; AI không auto-approve; proposer = Go deterministic + Python LLM hybrid.

## Rủi ro
- 3b cần provider LLM sống (z.AI đang 429 hết tiền — BytePlus fallback OK).
- Sample-data queries cho side-effect inference phải qua executor read-only (đã enforce) — tuyệt đối không mở đường đọc mới.
- Dashboard: người làm FE cần contract — Task 1 trả JSON model `WritePlaybook` như hiện tại, đừng đổi shape sau khi UI bắt đầu.
