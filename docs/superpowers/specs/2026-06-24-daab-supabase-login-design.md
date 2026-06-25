# DAAB → Supabase Login — Design Spec (2026-06-24)

> **Status:** DRAFT — awaiting approval before plan/implementation.
> **Scope:** Cho phép user đăng nhập DAAB bằng identity Supabase (project dùng chung của ecosystem), trong khi giữ login username/password cũ trong giai đoạn coexist. Đây là **slice login + identity**; RBAC provisioning (gán project) **không** đổi (dùng flow `project_members` sẵn có).
> **Mandate:** Supabase = **identity provider** (anh là ai); DAAB = **authorization** (anh được làm gì). DAAB **không** tạo/lưu credential của user Supabase.

---

## 1. Bối cảnh & mục tiêu

Hiện DAAB tự quản user (BA-014): login username/password → bcrypt → mint internal api-key → lưu iron-session ([auth.go](../../../ennam.kg.go/internal/handler/auth.go), [login/actions.ts](../../../ennam.kg.next/src/app/(auth)/login/actions.ts)). Ecosystem (AAAA + LAAM + DAAB) đã chốt **Supabase là identity provider dùng chung** (`decisions/ecosystem-direction-cto-approved-2026-06-24`).

**Mục tiêu slice này:**
- User đăng nhập DAAB bằng tài khoản Supabase (email/password trên project `nicrcubktflnwdkhotut` = "AM AI Project").
- DAAB **verify** JWT của Supabase (không tự xác thực credential), map sang DAAB user (`user_id`), mint internal api-key như cũ → phần còn lại của hệ thống (MCP, agent, dashboard) **không đổi**.
- Login username/password cũ **vẫn chạy song song** (coexist) để bootstrap admin + tránh lockout.

**Tại sao quan trọng:** đây là **chốt nền** cho memory-of-record user-scope (cần `user_id` ổn định, xuyên platform) và cho việc đồng bộ identity toàn ecosystem.

## 2. Non-goals (ngoài phạm vi slice này)

- ❌ Auto-provisioning quyền project (option email/domain hoặc sync `app_metadata`) — **defer**, chờ RBAC isolation threat-model.
- ❌ DAAB tạo user trên Supabase (Admin API / service_role) — user tạo ở **Supabase Dashboard** giai đoạn này.
- ❌ Đổi cơ chế auth của MCP/agent (api-key Bearer giữ nguyên).
- ❌ Migrate/đồng bộ 9 user Supabase hiện có vào DAAB hàng loạt — JIT theo từng lần login.
- ❌ Xóa endpoint `/api/v1/auth/login` (chỉ ẩn UI sau cutover; xóa ở slice dọn dẹp sau).
- ❌ SSO/refresh-token management nâng cao (xem §11 Open questions).

## 2.1 PRE-BUILD GATE — ✅ ĐÃ ĐÓNG (2026-06-24, verified end-to-end)

> Tiền đề "ES256, không cần secret" **đã được chứng minh trên TOKEN THẬT**, không chỉ JWKS.

**Cách verify:** tạo user thật `dragoon@exnodes.vn` qua GoTrue signup API (anon key) → nhận `access_token` thật → decode + verify chữ ký bằng public key JWKS (offline, PyJWT `ECAlgorithm.from_jwk`).

**Kết quả:**
- Header token thật: **`alg=ES256`**, **`kid=2dbb07a3-c643-4821-b608-ce016cc7e5a2`** (KHỚP JWKS).
- Payload: `iss=https://nicrcubktflnwdkhotut.supabase.co/auth/v1`, `aud=authenticated`, `sub=e7028d06-1f54-468e-837f-c58eb3258c7d`, `email=dragoon@exnodes.vn`.
- **`SIGNATURE VALID ✓`** verify bằng JWKS public key.

→ **Token thật ký ES256 bằng đúng key ở JWKS. Không có HS256 legacy active. DAAB verify chỉ cần JWKS public key — KHÔNG cần secret. Tiền đề đúng, build được.**

> ⚠️ **Phát hiện bảo mật (ngoài lề, cần lưu CTO):** **self-signup đang BẬT** trên project production — bất kỳ ai có anon key (publishable, lộ ở client) đều `POST /auth/v1/signup` tạo được account, **email auto-confirmed** (`email_verified:true`, không gửi mail xác nhận). Với DAAB điều này **không nguy hiểm trực tiếp** (JIT chỉ cấp `viewer`, 0 project → không thấy gì tới khi admin gán quyền) — đây chính là lý do chọn **JIT→viewer + no auto-grant**. Nhưng nên báo AAAA/CTO cân nhắc tắt open-signup hoặc giới hạn domain ở tầng Supabase.

## 3. Quyết định thiết kế (đã verify)

| Quyết định | Chọn | Bằng chứng / lý do |
|---|---|---|
| **Verify method** | JWKS public-key (ES256), cache, **không secret** | JWKS endpoint trả `alg=ES256`, EC P-256, `kid=2dbb07a3-c643-4821-b608-ce016cc7e5a2`. Asymmetric → DAAB chỉ cần public key. |
| **Cấu hình cần** | `SUPABASE_URL=https://nicrcubktflnwdkhotut.supabase.co` (+ project ref) | Đủ để dựng JWKS URL + validate `iss`. Không cần service_role/anon key cho verify. |
| **Provisioning** | JIT (tạo DAAB user lần login đầu) | Tránh migrate hàng loạt; map `sub` → `user_id`. |
| **Role mặc định JIT** | `viewer`, **không** project nào | Lowest-privilege; admin chủ động nâng. Đúng RBAC make-or-break gate (không auto-grant). |
| **RBAC / gán project** | Flow `project_members` sẵn có (admin) | Không đổi authorization model. |
| **Bootstrap admin** | (coexist) legacy `admin/Admin123`; (cutover) **admin-email allowlist** | Tránh lockout khi gỡ legacy. |
| **Coexist UI** | Trang login 2 đường: Email (Supabase) + Admin (username/password) | Legacy login y như hiện tại, tab riêng. |
| **JWT lib (Go)** | `lestrrat-go/jwx/v2` (JWKS native + cache) | go.mod chưa có JWT lib; jwx tự fetch+cache JWKS+verify ES256. |

## 4. Kiến trúc & luồng

```
┌── Browser (dashboard :3500) ───────────────────────────────┐
│  Tab "Email (Supabase)":                                    │
│   email+password → @supabase/supabase-js signInWithPassword │
│   → nhận Supabase JWT (access_token, ES256)                  │
│   → server action gửi JWT tới BFF                            │
└────────────────────────────┬───────────────────────────────┘
                             │ POST /api/v1/auth/supabase  { access_token }
                             ▼
┌── DAAB Go API (:8080) ─ SupabaseLogin handler ─────────────┐
│ 1. Verify JWT qua JWKS (ES256, cache):                      │
│      - chữ ký hợp lệ, chưa hết hạn (exp)                    │
│      - iss == <SUPABASE_URL>/auth/v1                         │
│      - aud == "authenticated"                                │
│ 2. Lấy claims: sub (Supabase UID), email                    │
│ 3. JIT-provision:                                            │
│      - tìm user theo supabase_user_id = sub                  │
│      - nếu chưa có → tạo DAAB user                           │
│          username=email, email=email, password_hash=NULL,   │
│          supabase_user_id=sub,                               │
│          role = (email ∈ allowlist ? 'admin' : 'viewer')    │
│      - cấp/đảm bảo internal api_key cho user (reuse plumbing)│
│ 4. Trả loginResponse{ user, api_key, requires_password_change=false }
└────────────────────────────┬───────────────────────────────┘
                             ▼
        iron-session lưu api_key (y như login cũ) → /
```

**Bất biến quan trọng:** sau bước 4, luồng giống hệt login cũ — `api_key` vào session; MCP/agent/dashboard không cần biết user đến từ Supabase.

## 5. Thay đổi data model — migration `000069`

`000069_add_supabase_user_id.up.sql`:
```sql
ALTER TABLE users ADD COLUMN supabase_user_id UUID;
CREATE UNIQUE INDEX idx_users_supabase_user_id
    ON users (supabase_user_id) WHERE supabase_user_id IS NOT NULL;
```
- Nullable: legacy user (username/password) giữ `NULL`.
- Unique-where-not-null: 1 Supabase identity ↔ 1 DAAB user.
- `down.sql`: drop index + column.

**Không** đổi CHECK role/status (vẫn `admin/developer/viewer`).
**Lưu ý JIT:** `username` NOT NULL + unique(LOWER) và `email` unique-where-not-null → set cả hai = email Supabase. Nếu email đã tồn tại ở 1 legacy user (vd có legacy `admin` với email trùng) → **link** supabase_user_id vào user đó thay vì tạo mới (xem §11 OQ-3).

## 6. Thay đổi backend (Go)

### 6.1 Config (`internal/config`)
- `SUPABASE_URL` (env `KG_SUPABASE_URL`) — bắt buộc để bật Supabase login; rỗng ⇒ endpoint trả 503 "supabase login disabled".
- `SUPABASE_ADMIN_EMAILS` (env `KG_SUPABASE_ADMIN_EMAILS`, CSV) — allowlist bootstrap admin (vd `admin@ennam.vn`).
- Dẫn xuất: JWKS URL = `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`; expected `iss` = `${SUPABASE_URL}/auth/v1`.

### 6.2 JWKS verifier (package mới, vd `internal/supabaseauth`)
- Dùng `jwx/v2/jwk.Cache` auto-refresh JWKS (TTL + refresh on unknown `kid` → handles key rotation).
- `VerifyToken(ctx, raw) (claims, error)`: parse + verify ES256, kiểm `exp`, `iss`, `aud=authenticated`. Trả `sub`, `email`.
- Fail-loud: lỗi verify → 401; JWKS không fetch được → 503 (không fallback "tin tạm").

### 6.3 Handler + route (`auth.go`)
- `POST /api/v1/auth/supabase` (PUBLIC, exempt khỏi auth middleware như `/auth/login`).
- Body `{ "access_token": "<supabase jwt>" }`.
- Verify → JIT (gọi service mới `UserService.LoginWithSupabase(ctx, claims)`) → trả `loginResponse` (tái dùng struct).
- Error: 401 token invalid/expired · 403 user disabled · 503 supabase disabled/JWKS down · 500 khác.

### 6.4 Service (`internal/service/user.go`) — ⚠️ ĐÃ VERIFY, KHÔNG tái dùng `CreateUser`

> **Quan trọng (verified):** `CreateUser` **bắt buộc** password (`ValidatePassword`+`HashPassword`) và set `status=pending_password_change` → **không dùng được** cho JIT Supabase (user không có password DAAB; status `pending` sẽ làm FE redirect `/change-password` — sai). Cần path tạo riêng.

- `LoginWithSupabase(ctx, sub, email) (*LoginResponse, error)`:
  1. tìm theo `supabase_user_id`:
     - **có** → dùng user đó.
     - **không, nhưng email trùng legacy user** → link `supabase_user_id` vào user đó (OQ-3).
     - **không hẳn** → tạo user mới: `username=email`, `email=email`, `password_hash=NULL`, `supabase_user_id=sub`, `display_name=email`, `role = allowlist? admin : viewer`, **`status=active`** (KHÔNG `pending_password_change`).
  2. `status==disabled` → trả lỗi `disabled` → handler 403.
  3. **Mint session api-key theo đúng pattern `Login`** ([user.go:362-391](../../../ennam.kg.go/internal/service/user.go)): revoke key cũ nếu label prefix `web-session-`; `keySvc.CreateKey{Label: "web-session-"+username, Role: user.Role.ToAPIKeyRole(), Internal: true, ProjectIDs: []}`; `UpdateAPIKeyID`; `UpdateLoginSuccess`.
  4. trả `LoginResponse{User, APIKey}`.
- Store mới: `GetUserBySupabaseID`, `SetSupabaseID`, `CreateSupabaseUser` (insert với password_hash NULL + supabase_user_id + status active). **Không** đụng `CreateUser`.
- Không cần `DummyPasswordHash` (không so password).

### 6.5 Middleware (verified)
- Thêm `/api/v1/auth/supabase` vào `isExemptPath` ([auth.go:292](../../../ennam.kg.go/internal/middleware/auth.go), case `/api/v1/auth/login`). **1 hàm dùng chung** cả auth + project middleware ([project.go:64](../../../ennam.kg.go/internal/middleware/project.go)) → chỉ sửa 1 chỗ + thêm case test `TestIsExemptPath`.

## 7. Thay đổi frontend (Next.js dashboard)

### 7.1 Login page — coexist 2 tab ([login/page.tsx](../../../ennam.kg.next/src/app/(auth)/login/page.tsx))
- Tab **"Email (Supabase)"** (mặc định, cho user thường): email + password → `@supabase/supabase-js` `signInWithPassword` (client) → lấy `access_token` → server action mới `supabaseLoginAction`.
- Tab **"Admin"** (legacy, có thể giấu sau link nhỏ): form username/password hiện tại, **không đổi**.

### 7.2 Server action mới `supabaseLoginAction` ([login/actions.ts](../../../ennam.kg.next/src/app/(auth)/login/actions.ts))
- Nhận `access_token` → `POST {GO_API_URL}/api/v1/auth/supabase` → set iron-session y như `loginAction` (apiKey, userId, role…). Map lỗi 401/403/503 → message thân thiện.

### 7.3 Supabase client
- `@supabase/supabase-js` + `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable key, an toàn để lộ client). Dùng **chỉ để** sign-in lấy JWT; không lưu Supabase session lâu dài (DAAB session là iron-session như cũ).

### 7.4 Sau cutover
- Ẩn tab "Admin"; trang chỉ còn Supabase. (Backend `/auth/login` vẫn sống tới slice dọn dẹp.)

## 8. RBAC & bootstrap admin

- **Identity** ở Supabase; **role + project** ở DAAB.
- JIT mặc định `viewer`, 0 project → admin gán quyền qua `POST /api/v1/projects/{id}/members`.
- **Bootstrap admin đầu tiên:**
  - *Coexist:* legacy `admin/Admin123` (DAAB) nâng role + gán project cho `admin@ennam.vn`.
  - *Cutover:* `admin@ennam.vn` ∈ `SUPABASE_ADMIN_EMAILS` → JIT thẳng thành `admin` (cửa thoát hiểm, không phụ thuộc legacy).
- **Gỡ legacy an toàn** chỉ khi: (1) allowlist có hiệu lực, (2) không còn legacy user nào khác ngoài `admin`, (3) login Supabase đã test E2E. Thứ tự: **ẩn UI legacy → giữ backend → xóa backend sau.**

## 9. An ninh (auth-sensitive — bắt buộc security-review)

- **Verify đầy đủ:** chữ ký ES256, `exp`, `iss` (chống token từ project khác), `aud=authenticated`. Từ chối `alg=none` / HS* (chỉ chấp ES256 từ JWKS).
- **Không secret phía DAAB** cho verify (giảm bề mặt rò). service_role key **không** dùng trong slice này.
- **JWKS rotation:** cache tự refresh khi gặp `kid` lạ; không hardcode key.
- **No auto-grant:** JIT chỉ cấp `viewer` → không leo thang quyền qua login.
- **PII:** email lưu DAAB users (đã có cột email). Không kéo thêm profile Supabase.
- **Anon/publishable key** lộ ở client là theo thiết kế Supabase (không phải secret). service_role **tuyệt đối không** xuống client.
- **Revocation lag (hệ quả của OQ-4 — quyết định có ý thức, không im lặng):** vì DAAB session độc lập sau khi mint api-key, **disable/delete user phía Supabase KHÔNG thu hồi access DAAB cho tới khi iron-session TTL hết hạn.** Chấp nhận trong slice này (khớp model legacy), nhưng **đặt TTL session ngắn** để chặn cửa sổ rủi ro. (Thu hồi tức thì = follow-up.)
- **Threat-model memory cross-platform** (RBAC isolation) vẫn là điều kiện cho việc *dùng* `user_id` này làm scope memory — ghi nhận, không thuộc slice login.

## 10. Coexist → cutover (lộ trình)

1. **Slice này (coexist):** thêm Supabase login bên cạnh legacy. Cả hai chạy.
2. Tạo/đảm bảo `admin@ennam.vn` trên Supabase; cấu hình allowlist; bootstrap role admin.
3. Người dùng chuyển dần sang Supabase login.
4. **Cutover UI:** ẩn tab "Admin".
5. **Dọn dẹp (slice sau):** xóa endpoint `/auth/login` + UI legacy + (tùy) cột password_hash cho user đã chuyển.

## 11. Open questions (cần chốt khi làm plan)

- **OQ-1 — JWT lib (✅ "Claude OAuth" đã verify, KHÔNG liên quan):** đã đọc [oauth.go](../../../ennam.kg.go/internal/handler/oauth.go) — "Claude OAuth" là **OAuth PKCE tới Anthropic làm AI provider** (`/auth/claude/authorize|callback|refresh`, `requireAdminRole`, inject token cho `claude_max`), **KHÔNG phải user-login**. → **Không có plumbing external user-identity để tái dùng**; go.mod trống JWT lib hợp lý; package mới là đúng. Còn lại chỉ là **chọn lib**: `lestrrat-go/jwx/v2` (đề xuất, JWKS cache + ES256 native) vs `golang-jwt/jwt/v5` + jwks fetcher. → quyết khi làm plan.
- **OQ-2 — Bật mặc định?** Slice này có set `KG_SUPABASE_URL` trong docker-compose ngay (bật Supabase login local) hay để tắt tới khi FE sẵn sàng?
- **OQ-2.5 — `username=email` (✅ verified OK):** validation legacy chỉ kiểm `required` + `≤255 ký tự` ([user.go:411-418](../../../ennam.kg.go/internal/service/user.go)), **không cấm `@`/charset** → `username=email` hợp lệ. Resolved.
- **OQ-3 — Email trùng legacy:** nếu Supabase email == email của 1 legacy DAAB user → **link** (gắn supabase_user_id vào user đó) hay **tạo mới**? Đề xuất: **link** (tránh nhân đôi identity). Cần xác nhận không có legacy user nào dùng email cá nhân trùng.
- **OQ-4 — Refresh/expiry:** DAAB session vẫn theo TTL iron-session cũ; có cần đồng bộ với exp của Supabase token không? Đề xuất: **không** trong slice này (DAAB session độc lập sau khi mint api-key).
- **OQ-5 — Logout:** logout DAAB chỉ xóa iron-session (như cũ); có cần gọi Supabase signOut phía client không? Đề xuất: có, cho sạch (client signOut + clear DAAB session).

## 12. Success criteria / test plan

**Backend (Go, table-driven + -race):**
- ✅ Token Supabase hợp lệ (ký bởi JWKS thật) → verify pass, trả claims đúng.
- ✅ Token sai chữ ký / hết hạn / sai `iss` / sai `aud` / `alg=none` → 401, **không** provision.
- ✅ JIT lần đầu: tạo user `viewer`, `supabase_user_id=sub`, api-key hợp lệ.
- ✅ Login lần 2 cùng `sub`: không tạo trùng, trả cùng user.
- ✅ Email ∈ allowlist → role `admin` (OQ-3 link-case nếu chốt link).
- ✅ User `disabled` → 403.
- ✅ `KG_SUPABASE_URL` rỗng → 503.
- ✅ Verify tool-count/invariant không liên quan (không thêm MCP tool).

**Integration:**
- ✅ Token thật từ `signInWithPassword` của `admin@ennam.vn` → login DAAB thành công, nhận api-key gọi được API có auth.

**Frontend (E2E Playwright):**
- ✅ Tab Email: login Supabase → vào dashboard.
- ✅ Tab Admin: `admin/Admin123` login (legacy) → vào dashboard (không regression).
- ✅ Sai mật khẩu Supabase → báo lỗi rõ.

**Security review:** security-reviewer agent (auth path).

## 13. Out of scope / follow-ups

- Auto-provisioning project (email/domain, app_metadata sync) — sau threat-model.
- DAAB tạo user qua Supabase Admin API (service_role).
- Xóa legacy `/auth/login` + password_hash cleanup.
- Memory-of-record cross-platform RBAC threat-model + test.
- LAAM/AAAA cùng dùng cơ chế identity này (ecosystem coordination — ai sở hữu tạo user).

---

## Verified facts (snapshot 2026-06-24)
- JWKS `https://nicrcubktflnwdkhotut.supabase.co/auth/v1/.well-known/jwks.json` → `alg=ES256`, EC P-256, `kid=2dbb07a3-c643-4821-b608-ce016cc7e5a2`.
- `auth.users` count = 9; `admin@ennam.vn` UID `1941b02f-74e7-4d9b-8a57-a905c352beac` (provider Email).
- `users` table: `password_hash` nullable; `username` NOT NULL unique(LOWER); `email` unique-where-not-null; role CHECK `admin/developer/viewer`; **no** `supabase_user_id` (→ migration 000069).
- `auth.go`: routes login/change-password/logout; `loginResponse{User, APIKey, RequiresPasswordChange}`.
- go.mod: **no** JWT lib (cần thêm).
- Latest migration: 000068.
- **"Claude OAuth"** = AI-provider OAuth PKCE tới Anthropic ([oauth.go](../../../ennam.kg.go/internal/handler/oauth.go): `/auth/claude/*`, `requireAdminRole`, claude_max token) — **KHÔNG** phải user-login. Không có user-identity plumbing để tái dùng.
- **username validation** = chỉ required + ≤255 ([user.go:411-418]) — `@` hợp lệ.
- **`CreateUser`** bắt buộc password + set `status=pending_password_change` → **không** dùng cho JIT; cần create path riêng (`password_hash=NULL`, `status=active`).
- **`Login`** ([user.go:318-402]) mint key `web-session-<username>` mỗi lần + revoke key `web-session-*` cũ → `LoginWithSupabase` theo cùng pattern.
- **`isExemptPath`** ([middleware/auth.go:292]) — 1 hàm, dùng chung auth+project middleware; thêm case `/api/v1/auth/supabase`.

## Re-check 2026-06-24 (lần "kiểm tra kĩ" thứ 2) — kết luận
Đã verify live code: **không lỗ hổng thiết kế lớn**. Sửa 5 điểm cho chính xác: OQ-1 (Claude OAuth không liên quan → resolved), OQ-2.5 (username=email OK → resolved), §6.4 (KHÔNG tái dùng CreateUser — password bắt buộc + status pending; cần create path riêng status=active), §6.5 (isExemptPath 1 chỗ), mint-key theo pattern Login. **PRE-BUILD GATE (§2.1) vẫn là điều kiện chặn build** (cần token thật xác nhận ES256 — chưa lấy được vì không có password user).
