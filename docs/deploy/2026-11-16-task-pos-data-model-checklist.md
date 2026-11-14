# Checklist deploy thứ Hai 16/11/2026 — nhánh `task/pos-data-model`

Nhánh này gồm: payment/subscription, kho dữ liệu POS T-log (landed), phân quyền theo cửa hàng (WS0) và các phần
làm thêm, "hỏi tự do trên dữ liệu T-log" (D1/D2, **đi kèm nhưng tắt bằng cờ**).
Nguồn: `ennam.kg.go/docs/ws0-delegation-runbook.md`, `ennam.kg.go/CLAUDE.md` (mục Landed store),
`LAAM/docs/DEPLOYMENT.md` §5.1, review cuối D1/D2 (`.superpowers/sdd/2026-11-14-landed-free-questions-store-scope/final-review.md`).

## 0. Trước khi bắt đầu

- [ ] Backup DB: `ennam_kg`, `ennam_landed` (nếu đã có), `laam`.
- [ ] Đồng hồ các máy chạy DAAB và LAAM đồng bộ NTP (vé WS0 lệch quá 60 s bị từ chối).
- [ ] Tạo một khoá ký vé: `kid:base64(≥32 byte)`. Đặt **giống hệt** vào DAAB `KG_DELEGATION_KEYS` và LAAM
      `DAAB_DELEGATION_KEYS`.
- [ ] Không đặt các cờ mới: DAAB `LANDED_NL_QUERY`, LAAM `LANDED_FREE_QUESTIONS` (bỏ trống = tắt).

## 1. Migration DB chính của DAAB (trước khi chạy kg-server mới)

Production không tự migrate. **Phải chạy trước khi khởi động kg-server mới**; nếu không, mọi câu hỏi NL và mọi
lần tra trạng thái sẽ lỗi (cột `requester_scope`).

- [ ] `kg-migrate up` trên `ennam_kg` tới **000100** (gồm 000096/097 landed, 000098 `delegation_required`,
      000099 loại data source `landed_system`, 000100 `ai_queries.requester_scope`). Kiểm tra `dirty = false`.

## 2. Kho landed (nếu dùng nạp POS T-log)

- [ ] DB `ennam_landed` + các role: chạy `scripts/landed/init.sql` (chỉ chạy được trên volume mới; với cụm đã có,
      tạo DB và role bằng tay theo file đó, rồi chạy các lệnh `REVOKE CONNECT` trong file).
- [ ] `make landed-migrate` tới **000005**.
- [ ] **000006 (hỏi tự do) — nên hoãn.** Không cần khi cờ tắt. Nó ghi lại toàn bộ bảng `landed_record` (thêm cột
      chi nhánh) và khoá bảng trong lúc chạy. Nếu vẫn chạy: chọn khung giờ vắng, dừng worker nạp dữ liệu, đặt
      `lock_timeout`, và chạy bằng tài khoản **có quyền sửa quyền trên các hàm hệ thống** (superuser của Postgres tự
      quản lý; trên RDS sẽ chỉ in cảnh báo — xem mục 6).

## 3. Deploy DAAB

- [ ] kg-server, kg-bridge (bản mới chuyển tiếp header `X-KG-Delegation`), worker Python.
- [ ] Log kg-server: có `landed ingest API enabled` (nếu dùng landed); **không** có
      `delegation tickets will be rejected: KG_DELEGATION_KEYS is empty`.
- [ ] Chạy **một** replica kg-server (yêu cầu sẵn có của phần landed).

## 4. Pack

- [ ] Chỉ phát hành pack mới (canonical 0.7.0 + khoá `scope: shared` của commit packs `3cef324`) **sau khi** kg-server
      mới đã chạy. Bản Go cũ từ chối khoá `scope` → toàn bộ pack không nạp được → mọi chỉ số trả 503.
- [ ] Nếu phải rollback kg-server: **rollback pack trước**.

## 5. Deploy LAAM

- [ ] `npm run db:migrate` trên DB `laam`.
- [ ] Env: `DAAB_DELEGATION_KEYS` (giống DAAB). Các kiểm tra trước deploy trong `LAAM/docs/DEPLOYMENT.md` §5.1
      (org connection phải có `project_id`, viết thường).
- [ ] Deploy **sau** DAAB.

## 6. Kiểm tra sau deploy (cờ tắt)

- [ ] Owner hỏi chỉ số trong chat → có số liệu.
- [ ] Member được giao 1 cửa hàng → Home/chat chỉ thấy cửa hàng đó; log DAAB có dòng `delegated data access` với
      đúng `stores`.
- [ ] Project mới gọi bằng key không gắn người dùng mà không có vé → `403 delegation_required` (đúng thiết kế;
      xem runbook WS0 để tắt cho project cần thiết).
- [ ] Ghi chú phát hành: các câu hỏi NL **đang chạy dở đúng lúc deploy** sẽ không đọc được kết quả qua vé (404).

## 7. Trước khi BẬT "hỏi tự do" (làm sau, không phải thứ Hai)

- [ ] Quyết định Postgres production: tự quản lý (thu hồi quyền hoạt động) hay RDS (không thu hồi được → tính
      năng tự khoá; cần phương án khác).
- [x] Bản sửa review cuối đã có (go `97b5f59`): DAAB kiểm tra `LANDED_AI_URL` thật sự đăng nhập là `landed_ai` ở
      chế độ chỉ đọc (lúc khởi động và ở mỗi câu hỏi), và tự kiểm tra lại trạng thái "sẵn sàng" định kỳ.
- [ ] Landed migration 000006 đã chạy (mục 2); `scripts/landed/ai-role.sql` với `LANDED_AI_PASSWORD`.
- [ ] Thu hồi `CONNECT` của PUBLIC trên các DB khác cùng cụm (`ennam_kg`, `postgres`, `template1`…), hoặc chặn
      `landed_ai` trong `pg_hba.conf` — `ai-role.sql` in cảnh báo cho từng DB còn vào được.
- [ ] Env DAAB: `LANDED_AI_URL`, `LANDED_CTX_KEYS`, rồi `LANDED_NL_QUERY=1`. Log phải có
      `landed free questions are ready`; nếu không, log nêu rõ điều kiện chưa đạt.
- [ ] Env LAAM: `LANDED_FREE_QUESTIONS=1`, `INTEL_DIRECT_QUERY_TOOLS=kg_query_datasource,kg_query_datasource_status`.
- [ ] Chạy thử: owner và một cửa hàng trưởng hỏi tự do; log DAAB `free question executed` đúng `stores`.
