# Báo cáo kiểm chứng end-to-end — Phân phối template ngành (pack distribution)

Ngày chạy: 2026-10-07 (giờ máy +07). Người chạy: agent Task 9 (SDD `2026-10-06-pack-distribution`).
Phạm vi: chỉ trong thư mục scratch, không docker, không đụng container hay DB thật (:5500, :5432). DB dev DAAB :5433 chỉ được dùng cho các test Go vốn đã dùng nó, qua `KG_TEST_DATABASE_URL` / `KG_TEST_DSN`.
Token: mỗi lần chạy sinh token ngẫu nhiên bằng `openssl rand -hex 24`, chỉ export trong môi trường của lệnh cần nó, và gửi cho curl qua stdin (`curl -K -`), nên không lọt vào argv. Không ghi token ra file. Sau khi chạy đã quét log tìm token: 0 lần xuất hiện.

Log: `docs/superpowers/test-results/2026-10-06-pack-distribution-logs/`. Các script driver (`phase*.sh`, server giả `fake_registry.py`, bộ sinh tarball tấn công `make_attacks.py`, các script tsx `laam_*.mts`) chỉ nằm trong scratch và đã bị xoá cùng scratch. Phần parity ở cuối `phaseA.log` lần đầu chạy lỗi vì tsx không cho top-level await trong file `.ts`; phần đó đã được chạy lại và ghi ở `phaseP.log`.

## Phiên bản được kiểm chứng

| Repo | HEAD | Commit liên quan |
|---|---|---|
| ennam.kg.go | `33a9c7b` | ff4ba64, 88b05ce, b585752, 156ecc5, d94294e, 33a9c7b, 317157b, 01f2ce5 |
| ennam.kg.next | `fd91fb0` | 704c814, fd91fb0 (follow-up đã land) |
| LAAM | `51651f7` | d40ad43, e0418dc, 61a89d2, 51651f7 |
| workspace | `888f4ea` | 9235e55, 888f4ea |
| ennam.kg.packs (scratch, chỉ local) | `37d2a62` lúc chạy; nay `3a0d0fa`, nhánh `main` | 37d2a62, 3a0d0fa (xem "Sau khi sửa") |

## Tổng hợp PASS/FAIL

**35 PASS, 2 FAIL lúc chạy.** Mục có dấu \* là PASS nhưng có lỗi cũ không thuộc phạm vi này (ghi rõ bên dưới).

> **Cập nhật sau khi chạy:** hai dòng FAIL (#11: chiếm lock stale khi nhiều tiến trình cùng chờ; #26: journal có `createdAt: ""`) đã được sửa sau đó, ở ennam.kg.go `717909e` và LAAM `6751d8d`. Xem mục "Sau khi sửa". Bảng dưới giữ nguyên kết quả của lần chạy gốc; các dòng này chưa được chạy lại end-to-end, chỉ có unit test của từng repo.

| # | Kiểm tra | Kết quả |
|---|---|---|
| 1 | Build `kg-pack-registry`, `kg-packs` (`go build -o …`) | PASS |
| 2 | Registry chạy với FS storage và 2 token; `/healthz` 200, `/readyz` 200, catalog rỗng `{"packs":[]}` | PASS |
| 3 | `_scripts/release.sh` build retail và pharmacy 0.2.0; build lại cho cùng byte (sha giống nhau), file `.sha256` khớp | PASS |
| 4 | Publish retail rồi pharmacy 0.2.0 → 201; catalog đúng (sha, size, changelog tiếng Việt, `latest`, `extends`) | PASS |
| 5 | Publish lại y hệt → 200 `identical` | PASS |
| 6 | Cùng version, nội dung khác → 409 `version_exists`; bản tải về vẫn là sha gốc | PASS |
| 7 | Publish bằng read token → 403; không token → 401 (cả PUT lẫn catalog) | PASS |
| 8 | `kg-packs fetch` retail rồi pharmacy vào PACKS_DIR rỗng; `versions`; layout đúng; `_staging` rỗng; nội dung active giống hệt cây nguồn | PASS |
| 9 | `fetch` khi thiếu token: thông báo nêu tên biến `PACKS_TOKEN`, không có giá trị | PASS |
| 10 | `TestRealPacksLoad` với PACKS_DIR = thư mục vừa fetch (test assert retail 27 / pharmacy 33 metric) | PASS |
| 11 | LAAM `vitest run src/lib/intel/pack` với PACKS_DIR = thư mục vừa fetch | **FAIL** (chập chờn: lần đầu 1/168 fail ở lock test; 5 lần sau 168/168 pass; xem lỗi #1) |
| 12 | Publish 0.3.0 (đổi 1 ngưỡng trên bản COPY), fetch: `_versions/retail/0.2.0` giữ đúng bản cũ (hash khớp), nội dung active khác | PASS |
| 13 | `kg-packs rollback` → active == 0.2.0, so từng byte (hash từng file) | PASS |
| 14 | Fetch lại version đang active → no-op ("already at") | PASS |
| 15 | Fetch lại 0.3.0 đã có trong `_versions` (nhánh `.stale-`) | PASS |
| 16 | Hạ version qua `fetch` → bị từ chối ("use rollback") | PASS |
| 17 | Parity Go ↔ LAAM: cài cùng chuỗi version vào hai thư mục → 146 file giống hệt, danh sách mục giống hệt, file record `.sha256` giống từng byte | PASS (khác quyền file, xem lỗi #4) |
| 18 | Chuỗi trộn trong một thư mục: Go fetch 0.2.0 → LAAM nâng 0.3.0 → Go rollback 0.2.0 → LAAM nâng lại 0.3.0; LAAM từ chối hạ version | PASS |
| 19 | 17 tarball tấn công → endpoint publish của registry: đều bị từ chối, không lưu gì (control hợp lệ 201) | PASS |
| 20 | 17 tarball tấn công → `kg-packs fetch` (server giả): đều bị từ chối, active giữ nguyên, staging sạch | PASS |
| 21 | 17 tarball tấn công → LAAM `installPack` (server giả): đều bị từ chối, active giữ nguyên, staging sạch | PASS |
| 22 | Không có file nào thoát khỏi PACKS_DIR (`ESCAPED-*`: 0; canary hardlink không đổi; không có file mới ngoài e2e/) | PASS |
| 23 | 6a: Go giữ lock → LAAM `busy` sau 2 s; với timeout 30 s LAAM chờ rồi chạy được | PASS |
| 24 | 6b: Node giữ lock → `kg-packs fetch` và `rollback` báo busy sau 2 s; với `--lock-timeout 30s` chờ rồi chạy được | PASS |
| 25 | 6c: crash giữa hai lần rename (3 trạng thái × `createdAt` RFC3339 / không có): hai runtime phục hồi ra cây giống hệt | PASS |
| 26 | 6c: cùng các trạng thái nhưng `createdAt: ""` | **FAIL** (Go từ chối, LAAM phục hồi; xem lỗi #3) |
| 27 | 6d: 7 swap.json hỏng hoặc độc hại: cả hai runtime từ chối, giữ nguyên file, không di chuyển gì | PASS |
| 28 | Go `go test -race -count=1 -v ./internal/handler/... ./internal/intel/... ./internal/packdist/... ./internal/packregistry/... ./cmd/...` (DB :5433) | PASS (1490 pass, 0 fail, 12 skip đều có sẵn từ trước) |
| 29 | LAAM vitest `src/lib/intel src/app/api/intel src/components src/app src/i18n` | PASS\* (3292 pass, 4 skip; 3 fail là lỗi ConstellationClient đã biết) |
| 30 | LAAM `tsc --noEmit` | PASS\* (chỉ có lỗi đã biết `executors.test.ts:260`) |
| 31 | LAAM eslint trên 44 file .ts/.tsx đã sửa | PASS (0 lỗi, 6 cảnh báo unused có sẵn) |
| 32 | `ennam.kg.next`: `npm run build` (có `/admin/templates`) và eslint 6 file đã sửa | PASS (0 lỗi, 6 cảnh báo có sẵn) |
| 33 | Ba file compose và Dockerfile: parse YAML, kiểm tra service, volume, env | PASS |
| 34 | Không có secret bị commit (grep các file đã đổi trong mọi repo) | PASS |
| 35 | `git ls-files cmd/kg-server` đủ file; clone sạch rồi `go build -mod=readonly ./cmd/...` | PASS |
| 36 | Không có token trong log registry, log CLI, log LAAM hay các log copy vào docs | PASS |
| 37 | Ở mọi lần chạy, registry/CLI chỉ ghi method, path, status (không có header) | PASS |

## Chi tiết từng bước

### Bước 1–2: Registry và publish

```bash
go build -o $E/bin/kg-pack-registry ./cmd/kg-pack-registry
go build -o $E/bin/kg-packs ./cmd/kg-packs
# token chỉ có trong môi trường của tiến trình registry:
KG_PACKS_STORAGE_DIR=$E/registry-store KG_PACKS_READ_TOKEN=$READ_T KG_PACKS_PUBLISH_TOKEN=$PUB_T \
  KG_PACKS_PORT=<cổng trống> $E/bin/kg-pack-registry &
bash $REPO/_scripts/release.sh retail $E/dist; bash $REPO/_scripts/release.sh pharmacy $E/dist
printf 'header = "Authorization: Bearer %s"\n' "$PUB_T" | curl -sS -K - -X PUT --data-binary @retail-0.2.0.tar.gz \
  -H "X-Pack-SHA256: $(shasum -a 256 retail-0.2.0.tar.gz | cut -c1-64)" -H "X-Pack-Changelog: <url-encoded>" \
  $BASE/v1/packs/retail/0.2.0
```

Kết quả quan sát được:
- retail-0.2.0 sha `dc92f9f8…aeafe`, 14374 B. pharmacy-0.2.0 sha `e7d600a9…19b8a`, 4360 B. Build hai lần cho cùng byte (trên macOS/bsdtar).
- PUT retail và pharmacy → 201. Catalog có `display_name`, `extends:["retail"]` cho pharmacy, `latest:"0.2.0"` và changelog tiếng Việt đúng.
- PUT lại cùng file → 200 `identical`. Bản sửa (thêm một dòng vào `pack.yaml`, vẫn là 0.2.0) → 409 `version_exists`. Tải về sau đó vẫn ra sha `dc92f9f8…`, header `X-Pack-Sha256` khớp.
- PUT bằng read token → 403 `forbidden`. Không token → 401 `unauthorized`. Catalog không token → 401.

### Bước 3: Fetch vào PACKS_DIR rỗng

```bash
PACKS_SOURCE=$BASE PACKS_TOKEN=$READ_T kg-packs fetch --packs-dir $P --pack retail --version 0.2.0
PACKS_SOURCE=$BASE PACKS_TOKEN=$READ_T kg-packs fetch --packs-dir $P --pack pharmacy --version 0.2.0
PACKS_DIR=$P kg-packs versions
PACKS_DIR=$P go test -count=1 -v -run TestRealPacksLoad ./internal/intel/
cd LAAM && PACKS_DIR=$P npx vitest run src/lib/intel/pack
```

- Kết quả: `retail: (none) -> 0.2.0`, `pharmacy: (none) -> 0.2.0`; `versions` in ra `pharmacy: active 0.2.0` và `retail: active 0.2.0`.
- Layout: `retail/`, `pharmacy/`, `_versions/<key>/0.2.0.sha256`, `_staging/` rỗng (lock đã nhả). `diff -r` với cây nguồn: giống hệt.
- `TestRealPacksLoad`: PASS cả hai subtest. Test assert `metrics=27` (retail) và `33` (pharmacy) ở `internal/intel/realpacks_test.go:31`.
- LAAM pack tests: lần đầu 167/168. Test fail là `lock.test.ts:81` "two waiters on the same dead lock never hold it at the same time" (`maxInside` = 2). Chạy riêng file đó 15 lần thì pass cả 15; chạy cả thư mục thêm 5 lần thì 168/168. Kết luận: test chập chờn, và nó lộ ra một race thật (lỗi #1).

### Bước 4: 0.3.0, rollback, hạ version, no-op

Bản COPY của repo được clone vào `e2e/repo3` (`git clone --no-local`). Ở đó `retail/laam/rules.yaml` dòng 19 và 23 đổi `0.95` thành `0.93` (RET-SALES-001), còn `pack.yaml` lên `0.3.0`. Repo gốc không bị động tới.

| Thao tác | Kết quả |
|---|---|
| publish 0.3.0 | 201; catalog `retail latest 0.3.0 ['0.2.0','0.3.0']` |
| fetch 0.3.0 | `retail: 0.2.0 -> 0.3.0`; `_versions/retail/0.2.0` có hash khớp snapshot; `diff` chỉ ra đúng dòng 19/23 và version |
| rollback 0.2.0 | `retail: 0.3.0 -> 0.2.0`; hash cây active == snapshot 0.2.0 (từng file) |
| fetch 0.2.0 lần nữa | `retail: already at 0.2.0` (no-op) |
| fetch 0.3.0 (đã có trong `_versions`) | `0.2.0 -> 0.3.0`, `_versions` gọn (không còn `.stale-`) |
| fetch 0.2.0 khi đang ở 0.3.0 | từ chối: `version is lower than the active version; use rollback` (exit 1), active vẫn 0.3.0 |

Parity (`phaseP.sh`):
- Go (`kg-packs fetch`) và LAAM (`installPack` qua tsx) cài cùng chuỗi retail 0.2.0 → pharmacy 0.2.0 → retail 0.3.0. Kết quả: 146 file giống hệt, danh sách mục giống hệt, record `0.2.0.sha256`/`0.3.0.sha256` giống từng byte (đều kết thúc bằng `\n`).
- Chuỗi trộn trong cùng thư mục cũng đúng: Go fetch 0.2.0 → LAAM 0.3.0 → Go rollback 0.2.0 (active == snapshot) → LAAM 0.3.0. LAAM từ chối hạ xuống 0.2.0 với `downgrade`.

### Bước 5: Tarball tấn công

`make_attacks.py` sinh 17 ca tấn công và 1 ca đối chứng. Mỗi ca là một pack retail thật, version 0.4.x riêng (cao hơn version active, chưa từng cài, nên không bị chặn sớm vì downgrade hay no-op), cộng với đúng một thay đổi độc hại. Mọi đích thoát đều trỏ vào `e2e/canary/`.

Phía client dùng server giả (`fake_registry.py`) mô phỏng API đọc. Catalog ghi đúng sha thật của body, trừ hai ca sai sha. Đối chứng: ca `control-valid` cài thành công bằng cả Go và LAAM.

| Ca | Registry PUT | `kg-packs fetch` | LAAM `installPack` |
|---|---|---|---|
| traversal `retail/../../…/canary/ESCAPED-trav` | 400 invalid_pack (not a relative path) | từ chối | `bad_pack` (path outside) |
| traversal `../canary/…` | 400 | từ chối | `bad_pack` |
| đường dẫn tuyệt đối | 400 | từ chối | `bad_pack` (absolute path) |
| symlink trỏ ra canary + file qua symlink | 400 (type '2') | từ chối | `bad_pack` (link) |
| hardlink tới canary (tuyệt đối) | 400 (type '1') | từ chối | `bad_pack` |
| hardlink nội bộ | 400 | từ chối | `bad_pack` |
| char device | 400 (type '3') | từ chối | `bad_pack` (special file) |
| thêm thư mục cấp đầu `other/` | 400 (outside retail/) | từ chối | `bad_pack` |
| tên trùng khi bỏ hoa/thường (`Canonical.yaml`) | 400 (differ only by case) | từ chối | `bad_pack` |
| gzip bomb 200 MiB số 0 (nén 219 KB) | 413 too_large | từ chối (extracted > 100 MiB) | `bad_pack` (too large unpacked) |
| `pack.yaml` 2 MiB | 400 (max 1 MiB) | từ chối | `bad_pack` |
| 2100 file thêm | 413 | từ chối (> 2000 entries) | `bad_pack` |
| `pack.yaml` sai version | 400 | từ chối | `bad_pack` |
| `pack.yaml` sai key | 400 | từ chối | `bad_pack` |
| nén 22 MB (> 20 MiB) | 413 (upload limit) | từ chối (stream exceeds limit) | `bad_pack` (download too large) |
| sai sha (catalog / header publish) | 400 checksum_mismatch | từ chối (checksum mismatch) | `bad_pack` |
| sai `X-Pack-SHA256` khi tải | 400 checksum_mismatch | từ chối | `bad_pack` |

Ca "catalog và header cùng ghi sha X nhưng body khác" (giả mạo thật sự) **không có trong e2e**: ở cả hai ca sai sha, Go dừng ngay ở bước so header với catalog. Ca này được phủ bằng đọc code và unit test:
- Go băm body trong lúc tải và so với sha của catalog trước khi giải nén (`internal/packdist/fetch.go:51-60`). Unit test `install_test.go:243-247` ("catalog sha mismatch", catalog và header đều sai, body thật) chạy xanh ở bước 7.
- LAAM: `install.ts` so `validateTarball(...).sha256` với catalog; unit test `install.test.ts:118`.

Ở cả 34 lần chạy client, cây PACKS_DIR (trừ `_staging`) trước và sau giống hệt nhau, active vẫn là 0.2.0 và `_staging` rỗng. Catalog của registry chỉ có thêm `0.4.1` (bản đối chứng). Kiểm tra thoát:
- `find e2e scratchpad /tmp -name 'ESCAPED-*'` trả về rỗng.
- Nội dung `canary/hardlink-target` không đổi.
- Không có file mới ngoài `e2e/` trong scratchpad.

### Bước 6: Lock và journal dùng chung

- **6a.** `kg-packs fetch` retail 0.4.1 được giữ trong lúc tải: server giả ngủ 8 s, và Go lấy lock trước khi tải. `owner.json` lúc đó là `{"pid":…,"host":…,"runtime":"go","startedAt":…}`. LAAM `installPack` và `withSharedLock` với timeout 2 s đều trả `busy` sau khoảng 2.0 s. Với timeout 30 s, LAAM chờ rồi xong sau 1.8 s, ngay khi Go nhả lock. Go kết thúc với `retail: 0.2.0 -> 0.4.1`.
- **6b.** tsx giữ lock 8 s (`owner.json` có `runtime:"node"`). `kg-packs fetch` và `kg-packs rollback` với `--lock-timeout 2s` báo "another template install is in progress", exit 1 sau 2 s. Với `--lock-timeout 30s`, rollback chờ rồi thành công.
- **6c.** Ba trạng thái crash, mỗi trạng thái chuẩn bị hai bản giống nhau (một cho Go, chạy `kg-packs versions`; một cho LAAM, chạy `withSharedLock` noop). Kết quả:

| Trạng thái | createdAt RFC3339 | không có createdAt | `createdAt: ""` |
|---|---|---|---|
| `<key>/` mất + parked `.prev-0.3.0` | cây giống nhau, active 0.3.0, journal xoá | giống nhau | **Go: "corrupt swap journal … parsing time"**, journal giữ, `retail/` vẫn mất; LAAM: phục hồi |
| `<key>/` có (0.2.0) + parked | giống nhau, active 0.2.0, parked chuyển về `_versions/retail/0.3.0` | giống nhau | Go từ chối như trên; LAAM phục hồi |
| mất + parked + stale `.stale-0.2.0` | giống nhau, active 0.3.0, stale trả về `_versions/retail/0.2.0` | giống nhau | Go từ chối; LAAM phục hồi |

- **6d.** Bảy journal hỏng: không phải JSON; `parked` thoát ra `../canary`; `parked` tuyệt đối; key `../canary`; `parked` không có dạng `.prev-`; `stale` thoát ra ngoài; `current` không khớp `parked`. Mỗi journal được thử bằng Go (`versions` và `rollback`) và LAAM (`withSharedLock` và `rollbackPack`). Cả hai đều từ chối (Go: "refusing invalid/corrupt swap journal"; LAAM: `needs_repair`). File journal giữ nguyên từng byte, cây thư mục không đổi, canary không đổi.

### Bước 7: Bộ test

```bash
KG_TEST_DATABASE_URL=<DSN :5433> KG_TEST_DSN=<DSN :5433> PACKS_DIR=$E/packsA \
  go test -race -count=1 -v ./internal/handler/... ./internal/intel/... ./internal/packdist/... ./internal/packregistry/... ./cmd/...
cd LAAM && PACKS_DIR=../packs npx vitest run src/lib/intel src/app/api/intel src/components src/app src/i18n
npx tsc --noEmit
node -e '<ESLint API, globInputPaths:false>'   # 44 file; glob của CLI vỡ với tên "(app)" và "[id]"
cd ennam.kg.next && npm run build
```

- **Go:** 14 package `ok`, 1490 PASS, 0 FAIL. Có 12 SKIP:
  - 11 test placeholder có sẵn (`Compare`/`Export`/`Favorite`, "requires handler wiring");
  - `TestHelperProcess` (helper của lock test).

  Không có test DB nào skip. Có 62 test về library/install/rollback/reload, trong đó có `TestPacksAdmin_LibraryWithFakeSource` và `TestPacksAdmin_LibraryCatalogTimeout`.
- **LAAM vitest:** 297 file (295 pass, 1 fail, 1 skip). 3292 pass, 4 skip, 3 fail. Ba fail đều là `ConstellationClient.test.tsx`, lỗi đã biết từ trước (task-7 report).
- **tsc:** chỉ có `src/lib/workflow/executors.test.ts(260,46)`, lỗi đã biết.
- **eslint:** LAAM 44 file: 0 lỗi, 6 cảnh báo có sẵn (`SettingsMenu.tsx` icon unused, `_a` trong `options/route.test.ts`). ennam.kg.next 6 file: 0 lỗi, 6 cảnh báo.
- **next build:** exit 0, có route `ƒ /admin/templates`.

### Bước 8: Kiểm tra tĩnh triển khai (không docker)

- **Compose** (PyYAML `safe_load`):
  - `docker-compose.yml` và `.release.yml` có service `kg-pack-registry`: entrypoint `/app/kg-pack-registry`, port `${KG_PACKS_PORT:-8090}:8090`, volume `packs_registry:/data/packs` có khai báo ở top-level, env token để trống mặc định, có healthcheck, network `ennam-kg`.
  - `kg-server` (dev và release) có `PACKS_DIR=/packs`, `PACKS_SOURCE`, `PACKS_TOKEN`, volume `${PACKS_HOST_DIR:-./packs}:/packs` (ghi được).
  - `LAAM/docker-compose.yml` `app`: cùng bộ env, volume `${PACKS_HOST_DIR:-../packs}:/packs`, network `default` và `ecosystem-net` (không có `ennam-kg`).
- **Dockerfile:** build `/bin/kg-pack-registry` (dòng 63) và `/bin/kg-packs` (dòng 67), copy sang `/app/` (dòng 88–89), `mkdir -p /data/packs && chown` (dòng 99).
- **Secret:** `git grep -nP '(TOKEN|SECRET|PASSWORD)=[^$\s{]'` trên các file đã đổi ở cả 5 repo: 0 kết quả. Grep dạng YAML `KEY: value` chỉ ra các giá trị nội suy `${…:-}`. Các mặc định dev có sẵn (`ennam_kg_dev`, internal dev token, session secret dev) không do các commit này thêm vào; đã kiểm bằng `git diff 9235e55~1..888f4ea`, mọi dòng token thêm mới đều là `${VAR:-}`.
- **File cần cho build:**
  - `git ls-files cmd/kg-server` ra `intel_wiring.go`, `intel_wiring_test.go`, `main.go`; không có file .go nào trong `cmd/kg-server`, `cmd/kg-pack-registry`, `cmd/kg-packs` chưa được track; `git check-ignore` không chặn file nào (`.gitignore` đã anchor `/kg-server`).
  - `git clone --no-local` rồi `go build -mod=readonly ./cmd/...` trên clone sạch: OK. `go vet` trên packdist, packregistry, kg-packs, kg-pack-registry: OK.

## Lỗi phát hiện (xếp theo mức độ)

1. **MEDIUM — Chiếm lock "stale" không loại trừ lẫn nhau khi có nhiều installer cùng chờ (cả hai runtime).**
   - Cơ chế: hai waiter cùng thấy lock của một tiến trình đã chết là stale. Waiter A chiếm lock (rename, xoá, `mkdir` lock mới). Waiter B, đã qua bước đọc lại, rename lock **còn sống** của A đi chỗ khác.
   - Go: `ennam.kg.go/internal/packdist/lock.go:187-213` (`takeOverIfStale`) không kiểm tra lại sau khi rename, nên xoá luôn lock của A.
   - LAAM: `LAAM/src/lib/intel/pack/dist/lock.ts:241-262` có kiểm tra lại, nhưng `rename(tomb, lockdir).catch(() => undefined)` ở dòng 256 nuốt lỗi. Trong khoảng hở đó một waiter thứ ba có thể đã `mkdir` lock rỗng, hoặc lệnh rename-back đè lên lock rỗng mới tạo.
   - Bằng chứng:
     - LAAM: **quan sát được**. `LAAM/src/lib/intel/pack/dist/lock.test.ts:81` fail 1 trong 21 lần chạy (`maxInside` = 2).
     - Go: **suy ra từ đọc code**, chưa tái hiện được. Go chỉ đọc lại trạng thái *trước* khi rename và xoá tomb mà không kiểm tra nó là lock nào.
   - Chỉ xảy ra khi có tiến trình cài đặt bị crash và có ≥ 2 installer chờ cùng lúc. Hiếm, nhưng hậu quả là hai swap chạy song song.
   - Hướng sửa: sau khi chiếm, ghi `owner.json` bằng `O_EXCL` rồi đọc lại, hoặc dùng một thư mục "takeover" riêng tạo bằng `mkdir` làm mutex cho bước chiếm.
2. **MEDIUM (rủi ro vận hành) — Byte tarball phụ thuộc nền tảng build.**
   - `release.sh` cho cùng byte trên cùng máy, nhưng chưa ai kiểm chứng rằng bản build macOS (bsdtar, gzip của macOS) và bản build CI (GNU tar, gzip của Ubuntu) giống byte.
   - Nếu ai đó publish 0.2.0 bằng tay từ macOS trước, workflow chạy khi đẩy tag sẽ nhận 409 và fail (`publish.yml` coi 409 là lỗi).
   - Quy tắc: **chỉ để CI publish**, xem phần bàn giao.
3. **LOW — Lệch giao thức journal với `createdAt: ""`.**
   - Go `journal.go:32` (`CreatedAt time.Time`) không parse được chuỗi rỗng, báo "corrupt swap journal", giữ journal và **không** phục hồi (`retail/` vẫn mất).
   - LAAM `lock.ts:134` chấp nhận và phục hồi.
   - Cả hai writer đều luôn ghi thời gian hợp lệ, nên chỉ gặp khi journal do người viết tay. Spec ghi "ISO-8601", tức Go đúng spec. Nên cho LAAM từ chối giống Go, hoặc cho Go chấp nhận chuỗi rỗng, để hai bên xử lý như nhau.
4. **LOW — Quyền file record khác nhau.**
   - Go ghi `_versions/<key>/<v>.sha256` với mode 0600 (`internal/packdist/installdisk.go:28`, `os.CreateTemp`). LAAM ghi 0644 (`install.ts:106`).
   - Nếu DAAB và LAAM dùng chung PACKS_DIR nhưng chạy với **uid khác nhau**, LAAM không đọc được record do Go tạo, và kiểm tra immutability báo lỗi.
   - Hôm nay cả hai image đều chạy uid 1000, nên chưa xảy ra. Nên `Chmod(0o644)` trước khi rename.
5. **LOW — `.gitignore` của repo ennam.kg.packs không có `_versions/` và `_staging/`.** Nếu dev mount một clone làm PACKS_DIR ghi được rồi cài từ UI, clone sẽ bẩn: file `retail/` đang track bị thay và có thư mục `_` chưa track. Ghi lại trong bàn giao: dev dùng `PACKS_HOST_DIR` riêng.
6. **LOW — `publish.yml:67` đưa publish token vào argv của `curl` trên runner.** GitHub che token trong log, nhưng token vẫn hiện trong danh sách tiến trình của runner. Nên đổi sang `curl -K -` hoặc `-H @file`.
7. **LOW (thẩm mỹ) — `_scripts/release.sh:60,80`:** tarball tạo bằng `mktemp` nên có mode 0600. Không ảnh hưởng tới upload.
8. **Vẫn mở từ Task 8:** compose của LAAM không nằm trên network `ennam-kg`, nên `PACKS_SOURCE` cho LAAM phải là địa chỉ HTTPS hoặc cổng host của registry.

## Sau khi sửa

Các lỗi ở trên đã được sửa sau lần chạy này. Mỗi repo có unit test riêng cho phần sửa; chưa chạy lại end-to-end.

| Lỗi | Sửa ở | Ghi chú |
|---|---|---|
| #1 chiếm lock stale đồng thời | ennam.kg.go `717909e`, LAAM `6751d8d` | Phải giữ thư mục claim `_staging/.lockdir.takeover` mới được chiếm lock, và phải đọc lại chủ lock trong lúc giữ claim. Lock không bao giờ bị đổi tên trở lại. Test stress (10 goroutine ở Go, 8 waiter ở LAAM) chạy lặp lại đều xanh. |
| #3 `createdAt: ""` | ennam.kg.go `717909e` | Go chấp nhận chuỗi rỗng hoặc thiếu, và từ chối chuỗi không phải RFC 3339, giống LAAM. |
| #4 quyền file record | ennam.kg.go `717909e`, LAAM `6751d8d` | `.sha256` và file đã giải nén là 0644, thư mục là 0755, với mọi umask. |
| #5 `.gitignore` repo pack | ennam.kg.packs `3a0d0fa` | Thêm `_versions/`, `_staging/`. |
| #6 token trong argv của curl | ennam.kg.packs `3a0d0fa` | `publish.yml` đưa token cho curl qua config trên stdin. |
| #7 mode tarball | ennam.kg.packs `3a0d0fa` | `release.sh` đặt mode cố định. |
| Mapping demo trong test | ennam.kg.go `01f2ce5`, LAAM `51651f7` | Fixture nằm ở `internal/intel/packtest/testdata/`; LAAM đọc version kỳ vọng từ `pack.yaml`. |
| Công cụ repo pack | ennam.kg.packs `37d2a62` | `scripts/` đổi thành `_scripts/`, nên gốc repo là một `PACKS_DIR` hợp lệ. |
| Dashboard: hiện "đã cài nhưng chưa nạp", nút Reload, lỗi nguồn rõ hơn | ennam.kg.next `bee6174` | Dùng các trường `loaded_version`, `needs_reload`, `registry_loaded`, `source_error_kind` và các mã lỗi `source_unauthorized`, `source_bad_response`. |
| Vòng final review: lock của chính tiến trình trước khi khởi động (chiếm ngay), lỗi `source_unauthorized` / `source_bad_response`, `needs_repair`, `loaded_version` / `needs_reload` / `registry_loaded`, tự thử nạp lại khi khởi động lỗi; LAAM "Match DAAB" không lùi phiên bản trên thư mục chung, câu chữ `version_not_stored` | ennam.kg.go `00d7cdc`, `6454e98`, `76e403e`; LAAM `ff14f56`; ennam.kg.next `bee6174`, `1bacfd9` | Chỉ có unit test; chưa chạy lại end-to-end. |

Lỗi #2 (byte tarball phụ thuộc nền tảng) và #8 (LAAM không ở mạng `ennam-kg`) là lưu ý vận hành; runbook đã ghi ở mục (b), (f) và (g).

## Chưa kiểm chứng

- UI trên trình duyệt chạy với backend thật: DAAB Template Library `/admin/templates`, LAAM Cài đặt → Mẫu theo ngành, badge "Update available" ở tab packs của dự án. Mới có build/lint và bản kiểm thị giác với fetch giả ở Task 6/7.
- Lưu trữ S3: chưa có implementation, mới chỉ có interface `Store`.
- Image và compose production: không chạy `docker build`/`docker compose`. Quyền sở hữu `/data/packs` trên named volume, mount `/packs` ghi được với uid 1000, healthcheck: chưa chạy thật.
- Workflow GitHub Actions `publish.yml`: chưa chạy trên GitHub, chưa có secret.
- Nhánh GNU tar của `release.sh` (chỉ chạy bsdtar trên macOS) và việc build trên CI có cho cùng byte với macOS hay không.
- DAAB `kg-server` đang chạy nạp lại pack dưới lock: chỉ kiểm qua handler test trong tiến trình, chưa có server thật.
- Stale lock trên host khác hoặc trên Windows (chiếm lock theo tuổi 15 phút): chỉ có unit test.
- TLS và registry đặt sau reverse proxy; nhiều upload đồng thời vào registry.

## Danh sách bàn giao (người dùng tự chạy, agent KHÔNG chạy)

> Repo pack đang nằm trong `/private/tmp/…/scratchpad/ennam.kg.packs`. Thư mục tạm có thể bị xoá khi khởi động lại máy, nên **đẩy hoặc sao lưu sớm**.

### 1. Đẩy repo ennam.kg.packs, chưa đẩy tag (sau khi đã duyệt nội dung)

```bash
SCRATCH=/private/tmp/claude-501/-Users-danhtrinh-Projects-Exnodes-EnnamKG-ennam-kg-workspace/b3aa9c12-69fd-45e5-88c2-b8cbae3dbf0a/scratchpad
cp -Rp "$SCRATCH/ennam.kg.packs" ~/Projects/Exnodes/EnnamKG/ennam.kg.packs   # bản sao bền, tuỳ chọn nhưng nên làm
cd ~/Projects/Exnodes/EnnamKG/ennam.kg.packs
git status --porcelain            # phải rỗng
git -C "$SCRATCH/ennam.kg.packs" log -1 --oneline   # 3a0d0fa chore: reproducible modes, safer publish workflow and main branch
git branch --show-current         # main (đã đổi tên sẵn, không cần đổi nhánh)
git remote add origin git@github-dragoon:En-Nam/ennam.kg.packs.git && git push -u origin main
```

Tag `v0.2.0` được đẩy ở bước 5, sau khi registry đã chạy. Đẩy tag sẽ chạy `publish.yml`.

**Quyết định trước khi push:** commit mới nhất không còn `_projects/`, nhưng **lịch sử** vẫn còn `_projects/pharmacy-chain/mapping.yaml`, đã có trong các commit `d7f20a4`, `5e1c892` và bị gỡ ở `1dd9b8b`. File này chứa UUID của dự án demo và nguồn dữ liệu demo, không có thông tin đăng nhập. Nếu không muốn đưa nó lên GitHub, chạy `git filter-repo --path _projects --invert-paths` trên bản sao trước khi push. Lệnh này đổi mọi hash của lịch sử, nên các hash ghi trong báo cáo này sẽ không còn khớp.

### 2. Gỡ `packs/` khỏi repo workspace, giữ `_projects/`

```bash
cd ~/Projects/Exnodes/EnnamKG/ennam.kg.workspace
git status --short packs                      # phải sạch
ls -A packs                                   # nếu có _versions/_staging do cài thử thì sao lưu trước
mkdir -p demo
git mv packs/_projects demo/projects          # mapping theo khách hàng ở lại workspace
git rm -r --cached packs                      # bỏ track retail/, pharmacy/, README.md (file vẫn còn trên đĩa)
rm -rf packs                                  # bootstrap chỉ clone vào đường dẫn chưa tồn tại
git diff .gitignore                           # .gitignore ĐÃ có thay đổi chưa commit từ trước: xem trước
printf '\n# Industry packs live in their own repo (ennam.kg.packs), cloned by scripts/bootstrap.sh\n/packs/\n' >> .gitignore
sed -i '' -E 's|^# (packs[[:space:]]+git@github-dragoon:)|\1|' scripts/repos.txt   # bỏ comment dòng packs
```

Sửa các tham chiếu `packs/_projects` thành `demo/projects` (runbook phân phối pack không còn nhắc tới đường dẫn này):
- dòng chú thích ở `demo/projects/pharmacy-chain/mapping.yaml:4`;
- `scripts/demo_data/schema/extension.sql:2`.

Trong ennam.kg.go chỉ có chú thích nhắc tới đường dẫn này, có thể để nguyên: `internal/intel/mapping_file.go:13`, `internal/intel/packtest/testdata/pharmacy-chain-mapping.yaml:4`.

```bash
git add -p .gitignore                         # chỉ chọn hunk /packs/, không gom thay đổi có sẵn
git add scripts/repos.txt demo/projects scripts/demo_data/schema/extension.sql
git commit -m "chore: packs moved to ennam.kg.packs; demo project mappings kept in demo/projects"
bash scripts/bootstrap.sh                     # clone packs/ từ En-Nam/ennam.kg.packs
```

Dev: thư mục `./packs` giờ là một clone git. Nếu muốn cài, cập nhật hay quay lại từ UI hoặc CLI, đặt `PACKS_HOST_DIR` sang một thư mục riêng, ví dụ `~/ennam-packs-installed`, rồi `kg-packs fetch` vào đó. Làm vậy để clone không bị bẩn (lỗi #5).

### 3. Token và `PACKS_HOST_DIR` trên server (DevOps / người vận hành; ghi vào `.env` của server, không commit)

- Máy registry: `KG_PACKS_READ_TOKEN` và `KG_PACKS_PUBLISH_TOKEN`, mỗi cái sinh bằng `openssl rand -hex 32`, hai giá trị khác nhau.
- Máy DAAB (`.env` của workspace):
  - `PACKS_HOST_DIR=/srv/ennam/packs`; tạo trước bằng `sudo install -d -o 1000 -g 1000 /srv/ennam/packs`;
  - `PACKS_SOURCE=http://kg-pack-registry:8090` nếu cùng network `ennam-kg`, hoặc URL HTTPS;
  - `PACKS_TOKEN=<read token>`.
- Máy LAAM (`LAAM/.env`): `PACKS_HOST_DIR` (dùng chung thư mục với DAAB nếu cùng máy), `PACKS_SOURCE=<URL HTTPS hoặc cổng host>` vì LAAM không ở trên `ennam-kg`, `PACKS_TOKEN=<read token>`.

### 4. Rebuild image và recreate container (người dùng tự chạy)

Dev stack (build tại chỗ):

```bash
cd ~/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose build kg-server dashboard          # image kg-server cũng chứa /app/kg-pack-registry và /app/kg-packs
docker compose up -d kg-pack-registry kg-server dashboard
cd LAAM && docker build -t laam-app:latest . && docker compose up -d app
```

Production (`docker-compose.release.yml` dùng image dựng sẵn `daab-server:${KG_RELEASE_TAG:-v2.5.0}`, nên `docker compose build` ở đây không làm gì). Tag cũ **không có** `/app/kg-pack-registry` và `/app/kg-packs`, nên registry sẽ không chạy được và lệnh `exec` ở bước 6 sẽ fail. Cần:
1. Build và push một image release mới từ `ennam.kg.go` HEAD (≥ `33a9c7b`), image dashboard từ `ennam.kg.next` (≥ `fd91fb0`), và image LAAM, theo quy trình release thường lệ.
2. Đặt `KG_RELEASE_TAG=<tag mới>` (và `KG_IMAGE_PREFIX` nếu dùng) trong `.env` của server.
3. Chạy `docker compose -f docker-compose.release.yml pull`, rồi `docker compose -f docker-compose.release.yml up -d kg-pack-registry kg-server dashboard`.
4. Kiểm tra: `curl -fsS http://<host>:8090/healthz`.

### 5. Publish 0.2.0 (chỉ qua CI)

Điều kiện trước khi đẩy tag:
- Registry production đã chạy (bước 4) và runner GitHub gọi tới được qua HTTPS (DevOps).
- Đã đặt secret của repo: `gh secret set PACKS_REGISTRY_URL --repo En-Nam/ennam.kg.packs` và `gh secret set PACKS_PUBLISH_TOKEN --repo En-Nam/ennam.kg.packs` (nhập giá trị khi được hỏi, không truyền trên dòng lệnh).
- **Không publish 0.2.0 bằng tay.** Để CI là bên publish duy nhất (lỗi #2).

```bash
cd ~/Projects/Exnodes/EnnamKG/ennam.kg.packs
git tag -a v0.2.0 -m "Release 0.2.0"
git push origin v0.2.0
# kiểm tra: workflow xanh; catalog có retail và pharmacy 0.2.0
```

### 6. Cài pack trên host DAAB và LAAM

```bash
cd ~/Projects/Exnodes/EnnamKG/ennam.kg.workspace           # production: thêm -f docker-compose.release.yml
docker compose exec kg-server /app/kg-packs fetch --pack retail --version 0.2.0
docker compose exec kg-server /app/kg-packs fetch --pack pharmacy --version 0.2.0
docker compose exec kg-server /app/kg-packs versions
# nạp lại DAAB: nút nạp lại trong Template Library, hoặc POST /api/v1/admin/packs/reload (global admin)
```

LAAM:
- Nếu dùng chung `PACKS_HOST_DIR` với DAAB, không cần làm gì thêm.
- Nếu dùng thư mục riêng, có hai cách. Cách 1: Cài đặt → Mẫu theo ngành → Cài retail rồi pharmacy 0.2.0. Cách 2: chạy `kg-packs` trên host với uid 1000:
  `sudo -u '#1000' env PACKS_SOURCE=… PACKS_TOKEN=… ./kg-packs fetch --packs-dir /srv/laam/packs --pack retail --version 0.2.0`, rồi làm tương tự với pharmacy.

### 7. Chuyển cho DevOps

Gửi mục (g) "Yêu cầu hạ tầng cho DevOps" trong `docs/superpowers/runbooks/2026-10-06-pack-distribution-and-deploy.md`. Kèm theo:
- lỗi #2 (chỉ CI publish);
- cần image release mới (bước 4);
- LAAM cần URL HTTPS của registry;
- registry chưa có TLS riêng, nên đặt sau reverse proxy;
- `kg-pack-registry` sẽ restart liên tục nếu chưa đặt token (đây là thiết kế cố ý);
- sao lưu volume `packs_registry`.
