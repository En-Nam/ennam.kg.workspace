# Checklist deploy — tăng tốc mở phiếu và bằng chứng (landed `000007`)

Gồm: landed migration `000007` (DAAB, `ennam.kg.go` commit a1749db..dc0d3a2) và thay đổi route phiếu của LAAM
(commit a76863e0, fde88155).
Nguồn: `docs/superpowers/specs/2026-11-19-landed-receipt-speed-design.md`, `ennam.kg.go/CHANGELOG.md`, `LAAM/CHANGELOG.md`.

Đo trên production trước thay đổi: mở phiếu 4,2–5,2 s; bằng chứng 25 dòng 1,4 s; 100 dòng 2,3 s.
Đo cục bộ: truy vấn bằng chứng 947 ms → khoảng 67 ms (dưới `landed_engine`).

## 0. Trước khi bắt đầu

- [ ] Có sự đồng ý của owner cho từng bước deploy (main → nhánh deploy-*).
- [ ] Backup DB `ennam_landed`.
- [ ] Lấy thời gian chạy migration `000006` trước đó (nó ghi lại cùng bảng `landed_record`) làm ước lượng cho `000007`.
      Cục bộ `000007` chạy 4 s cho khoảng 155 nghìn dòng.
- [ ] Chọn giờ vắng: cột STORED làm ghi lại **toàn bộ** `landed_record`, và build index chặn ghi của worker nạp
      (bảng phân vùng không dùng được `CONCURRENTLY`). Tạm dừng worker nạp, đặt `lock_timeout`.

## 1. Migration `000007` trên RDS (làm trước khi deploy code)

- [ ] Chạy bằng tài khoản `landed_maintenance`: `make landed-migrate` (cách chạy landed migration xem
      `docs/deploy/2026-11-16-task-pos-data-model-checklist.md` mục 2). Kiểm tra version = 7, `dirty = false`.
- [ ] Code DAAB cũ vẫn chạy bình thường sau migration (chỉ có thêm cột); code mới tự nhận cột.

## 2. Deploy DAAB (chỉ khi owner đồng ý)

- [ ] Merge nhánh vào `main`, rồi `deploy-dev` (kèm `deploy-dev-bridge` / `deploy-dev-worker` nếu có đổi).
- [ ] Không có lỗi trong log kg-server; engine nhận cột ở lần truy vấn landed đầu tiên.

## 3. Deploy LAAM (sau DAAB, chỉ khi owner đồng ý)

- [ ] Merge vào `main`, rồi nhánh deploy của LAAM. Không có migration hay env mới.
- [ ] Thành viên mở phiếu bình thường; người không phải thành viên nhận 404 ngay.

## 4. Kiểm tra sau deploy

- [ ] `EXPLAIN` truy vấn theo `sale_id` dưới `landed_engine` có `Index Cond` trên `sale_id_key`.
- [ ] Đo lại trên production: mở phiếu, bằng chứng 25 dòng, bằng chứng 100 dòng; so với số trước (4,2–5,2 s / 1,4 s / 2,3 s).
- [ ] Con số trên các phát hiện (số tiền, số dòng bằng chứng) **không đổi** so với trước deploy.
- [ ] Hỏi tự do: câu lọc bằng `=` trên `sale_id` / `product_id` dùng index. **Không** hứa join giữa các view pos nhanh hơn:
      khoá join không được đẩy vào view `security_barrier` nên không dùng index key.

## 5. Rollback

- [ ] Roll back hoặc khởi động lại DAAB **trước** khi chạy `000007 down`. Engine nhớ "đã có cột" suốt vòng đời tiến trình;
      nếu chạy down trước, mọi truy vấn landed lỗi cho tới khi DAAB restart.
- [ ] Chạy down một bước bằng `landed_maintenance` (`make landed-migrate CMD=down`). `down` dùng `DROP COLUMN ... CASCADE`
      nên cũng xoá các view AI của pos; DAAB tạo lại bằng `SyncAIViews` khi khởi động.
- [ ] Khởi động DAAB (nếu chưa), xác nhận view AI đã được tạo lại và truy vấn landed chạy bình thường.
- [ ] LAAM không cần rollback riêng; thay đổi của nó độc lập với migration.
