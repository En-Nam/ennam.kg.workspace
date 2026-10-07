# Runbook: Chuyển DAAB + LAAM sang dữ liệu thật của khách hàng

**Ngày:** 2026-10-02
**Trạng thái:** Ghi chú để dùng khi có dữ liệu thật — **chưa áp dụng cho beta/demo**
**Liên quan:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (§12b, §14)

Beta/demo chạy trên dữ liệu giả `pharmacy_demo`. File này gom các việc phải làm/kiểm tra **khi kết nối DB, dữ liệu và tài liệu thật của khách**, gồm cả các mục bảo mật/pháp lý đã thống nhất **để sau** (quyết định 2026-09-28).

---

## 1. Nguyên tắc
Chuyển sang khách thật = **cấu hình**, không viết lại engine. Pack (metric SQL, evidence, rule, scenario, forecast), engine LAAM, 4 tool `kg_*` và UI Home giữ nguyên.

## 2. Chỉ cấu hình (mỗi khách)
| Việc | Ở đâu |
|---|---|
| Kết nối DB (read-only, ưu tiên replica) | DAAB data source |
| Mapping bảng/cột → entity canonical, chuẩn hoá enum | `mapping.yaml` (LLM đề xuất, người duyệt) |
| Chọn pack | `pack_install` |
| Múi giờ, ngôn ngữ, user sở hữu job | `business_project` |
| KPI target | Upload "Dữ liệu bảng" |
| Ngưỡng, trọng số ưu tiên, preset kịch bản | `rule_override` |
| User, persona, chi nhánh | `user_scope` |
| Giờ chạy, lookback | `analysis_job`, header metric / override |

## 3. Có thể phải code thêm (tuỳ khách)
| Trường hợp | Việc cần làm |
|---|---|
| DB MSSQL/MySQL | Thêm dialect (sinh CTE + đổi tham số) |
| Dữ liệu canonical chưa có (NDC, lô/hạn dùng, PBM…) | Mở rộng entity trong pack, nâng version pack — không sửa core |
| Nguồn xoá lịch sử sớm / cần join nhiều hệ thống / chỉ có file, SFTP | Bật `landed`, reference pushdown, SFTP |
| DB chậm, dữ liệu lớn (query > 30s, vượt giới hạn dòng) | Replica/index phía khách, chia cửa sổ nhỏ, timeout riêng theo metric |
| File định dạng lạ (nhiều header, ô gộp…) | Bổ sung parser/tuỳ chọn upload |

## 4. Bắt buộc trước khi dùng dữ liệu thật

### 4.1 Kỹ thuật
- [ ] **DAAB tự kiểm tra quyền chi nhánh (row-level)** và biết user cuối: mỗi user một API key DAAB, hoặc header acting-user có ký. Hiện DAAB chỉ biết API key (`handler/authz.go`, `bridge/serve.go`).
- [ ] **Chặn request không xác thực** đang được cho qua `requireProjectAccess` (`ennam.kg.go/internal/handler/authz.go:37-38`).
- [ ] **Che cột thông tin cá nhân** trong evidence (tên, SĐT, ngày sinh, địa chỉ của khách/bệnh nhân); không đưa vào `metric_value`; token hoá `customer_id` nếu cần.
- [ ] **Chỉ map cột cần thiết** (minimum necessary) — không map cột định danh cá nhân nếu không có metric nào dùng.
- [ ] Rà dữ liệu gửi tới LLM: brief chỉ nhận số tổng hợp; Ask LAAM / `kg_query_datasource` có thể gửi dòng dữ liệu cho LLM — xem 4.2.
- [ ] Log, crash report, telemetry, backup, dump DB debug không chứa dữ liệu cá nhân; `ai_queries` có lưu SQL/kết quả — rà lại.

### 4.2 Bảo mật / pháp lý (để sau — làm riêng khi triển khai)
Ghi lại từ thảo luận 2026-09-28; **không phải ý kiến pháp lý**, cần luật sư/compliance của khách xác nhận.
- **HIPAA (Mỹ)**: nhà thuốc là covered entity; đơn thuốc, claim, thông tin bệnh nhân là **PHI**. Team xử lý PHI thay khách ⇒ **Business Associate** ⇒ cần **BAA** trước khi chạm dữ liệu thật; tuân thủ Security Rule (mã hoá, phân quyền, audit, báo cáo sự cố) và "minimum necessary".
- **Texas HB 300**: chặt hơn HIPAA (đào tạo nhân sự, phạt, thông báo sự cố).
- **Hợp đồng PBM/payer**: dữ liệu giá/reimbursement thường cấm chia sẻ bên thứ ba — khách xác nhận.
- **PCI DSS**: không kéo cột thẻ thanh toán.
- **Luật Bảo vệ dữ liệu cá nhân Việt Nam** (hiệu lực 2026-01-01) khi team ở VN truy cập dữ liệu cá nhân.
- **Truy cập từ Việt Nam (offshore)**: nhiều khách Mỹ cấm trong hợp đồng — hỏi rõ; support remote (Tailscale/SSH) cần chấp thuận.
- **LLM**: gửi PHI cho LLM không có BAA là vi phạm. Chỉ dùng provider có BAA, hoặc model nội bộ; LLM chỉ nhận số tổng hợp + định danh đã token hoá.

### 4.3 Triển khai trên server khách + model AI nội bộ (nếu khách yêu cầu)
- Giải quyết phần lớn rủi ro gửi dữ liệu ra ngoài; **vẫn** cần BAA nếu team cài đặt/bảo trì/debug, và chấp thuận truy cập offshore.
- Chất lượng model nội bộ: ảnh hưởng mạnh tới NL→SQL (`kg_query_datasource`), chat + gọi tool, trích xuất/embedding khi ingest; ảnh hưởng **ít** tới briefing (số do SQL/code tính). **Chạy eval trước khi hứa với khách** (12 câu demo pharmacy + eval LAAM).
- Code đã có nền: LAAM hỗ trợ `ollama`; DAAB có đường OpenAI-compatible với `base_url` — cần test thực tế, đổi cả model embedding.
- Phần cứng: model 7–14B (~1 GPU 24GB) chỉ đủ diễn giải; 30–70B (48–80GB VRAM) mới ổn cho NL→SQL/tool. Kiểm tra license model (thương mại).
- Vận hành: bộ cài chuẩn, nâng cấp (kể cả air-gapped), giám sát, backup; tránh lệch phiên bản giữa các khách.
- Hỗ trợ 3 chế độ qua cấu hình: cloud API (demo) / hybrid (dữ liệu ở khách, LLM API có BAA nhận số tổng hợp) / hoàn toàn nội bộ.

## 5. Dữ liệu thật "bẩn" hơn — quy trình
- Enum/giá trị lạ, NULL, mã chi nhánh không khớp ⇒ mapping chuẩn hoá + báo cáo validation; không map được ⇒ `data_status = incomplete`.
- Thiếu dữ liệu ⇒ metric/rule tự tắt và báo lý do.
- **Shadow mode 2–4 tuần**: sinh finding nhưng chỉ nội bộ + người phụ trách phía khách xem; chỉnh `rule_override`; rồi mới bật brief cho mọi user.
- Không có ground truth ⇒ đo bằng tỉ lệ dismiss "không đúng" + backtest dự báo trên lịch sử thật.
- Lịch sử ngắn ⇒ forecast tự hạ độ tin cậy hoặc không dự báo.

## 6. Tài liệu (docs) của khách
- Văn bản (chính sách, quy trình, hợp đồng) ⇒ đường **"Tài liệu"** hiện có (Knowledge Sources → KG), dùng cho Ask LAAM và ngữ cảnh; không dùng tính chỉ số.
- Tài liệu chứa bảng số (bảng giá, target) ⇒ đường **"Dữ liệu bảng"**.

## 7. Checklist onboarding
1. Tạo `business_project` (múi giờ, ngôn ngữ, user sở hữu).
2. Hoàn tất mục 4.1 (và 4.2 nếu dữ liệu có PHI).
3. Kết nối DB (read-only, replica) → sync schema.
4. LLM đề xuất mapping → người duyệt → validation đến khi `data_status` sạch.
5. Bật pack; upload target; khai báo `user_scope`.
6. Backfill metric (chia cửa sổ) → đối chiếu vài số với báo cáo khách đang dùng.
7. Shadow mode 2–4 tuần, chỉnh ngưỡng.
8. Bật brief; theo dõi tỉ lệ dismiss và độ chính xác dự báo.
