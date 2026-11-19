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
      (bảng phân vùng không dùng được `CONCURRENTLY`). Tạm dừng worker nạp.
- [ ] Đặt `lock_timeout` cho phiên migration (`make landed-migrate` không có cờ cho việc này), bằng tài khoản master:
      `ALTER ROLE landed_maintenance IN DATABASE ennam_landed SET lock_timeout = '10s';` — chạy migration xong thì
      `ALTER ROLE landed_maintenance IN DATABASE ennam_landed RESET lock_timeout;`. Nếu migration hết thời gian chờ khoá:
      nó tự rollback (một transaction); kiểm `version`, nếu bị đánh dấu `dirty` ở 6 thì `force 6`, rồi chạy lại lúc vắng hơn.

## 1. Migration `000007` trên RDS (làm trước khi deploy code)

- [ ] Chạy bằng tài khoản `landed_maintenance`: `make landed-migrate` (cách chạy landed migration xem
      `docs/deploy/2026-11-16-task-pos-data-model-checklist.md` mục 2). Kiểm tra version = 7, `dirty = false`.
- [ ] Code DAAB cũ vẫn chạy bình thường sau migration (chỉ có thêm cột); code mới tự nhận cột.

## 2. Deploy DAAB (chỉ khi owner đồng ý)

- [ ] Merge nhánh vào `main`, rồi `deploy-dev` (kèm `deploy-dev-bridge` / `deploy-dev-worker` nếu có đổi).
- [ ] Không có lỗi trong log kg-server; engine nhận cột ở lần truy vấn landed đầu tiên.
- [ ] Nếu lỡ deploy DAAB **trước** khi chạy `000007`: engine tự nhận cột trong vòng 2 phút, nhưng view AI của câu hỏi tự do chỉ
      được tạo lại khi DAAB khởi động / đổi pack → restart DAAB một lần sau khi migration xong.

## 3. Deploy LAAM (sau DAAB, chỉ khi owner đồng ý)

- [ ] Merge vào `main`, rồi nhánh deploy của LAAM. Không có migration hay env mới.
- [ ] Thành viên mở phiếu bình thường; người không phải thành viên nhận 404 ngay.

## 4. Kiểm tra sau deploy

- [ ] `EXPLAIN` truy vấn theo `sale_id` dưới `landed_engine` có `Index Cond` trên `sale_id_key`.
- [ ] Đo lại trên production: mở phiếu, bằng chứng 25 dòng, bằng chứng 100 dòng; so với số trước (4,2–5,2 s / 1,4 s / 2,3 s).
- [ ] Con số trên các phát hiện (số tiền, số dòng bằng chứng) **không đổi** so với trước deploy.
- [ ] Riêng câu hỏi tự do (chat tự viết SQL): `sale_id` / `product_id` rỗng (`''`) giờ đọc là NULL trong view pos, nên câu
      đếm/lọc trên id rỗng có thể ra số khác (dữ liệu id rỗng vốn là dữ liệu hỏng).
- [ ] Hỏi tự do: câu lọc bằng `=` trên `sale_id` / `product_id` dùng index. **Không** hứa join giữa các view pos nhanh hơn:
      khoá join không được đẩy vào view `security_barrier` nên không dùng index key.

## 5. Rollback

Thường **không cần** chạy `000007 down`: muốn bỏ thay đổi thì chỉ cần roll back DAAB về bản trước — bản cũ không đọc các cột
mới, cột thừa vô hại. Chỉ khi thật sự phải xoá cột, làm đúng thứ tự:

- [ ] Chạy down một bước bằng `landed_maintenance` (`make landed-migrate CMD=down` — lùi **một** bước, không phải `down-all`).
      `down` dùng `DROP COLUMN ... CASCADE` nên cũng xoá các view AI của pos.
- [ ] **Ngay sau đó luôn restart mọi bản DAAB** (kể cả khi vừa restart trước đó). DAAB đang chạy nhớ "đã có cột" suốt vòng đời
      tiến trình: từ lúc down tới lúc restart, truy vấn landed của engine lỗi. Restart cũng tạo lại view AI (`SyncAIViews`).
      Đừng restart DAAB *trước* khi down — DAAB mới khởi động sẽ thấy cột còn đó và lại nhớ "đã có cột".
- [ ] Xác nhận view AI đã được tạo lại và trang phát hiện / mở phiếu chạy bình thường.
- [ ] LAAM không cần rollback riêng; thay đổi của nó độc lập với migration.
