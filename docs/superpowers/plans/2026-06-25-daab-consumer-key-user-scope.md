# DAAB Consumer-Key + User-Scope (D3 / g2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Làm `user_id` scoping của memory-of-record LIVE (gate g2b) + định nghĩa consumer-key class (D3), để bật AAAA/LAAM tiêu thụ `kg_recall`/`kg_remember` an toàn theo từng user.

**Architecture:** Thêm forward-column `api_keys.user_id` (key mang user). Auth nạp nó vào `DeveloperIdentity.UserID`. Handler `kg_remember`/`kg_recall` truyền `identity.UserID` xuống store (store đã sẵn field + filter — KHÔNG đổi store). Các đường tạo key (login/JIT, dashboard, token-exchange consumer) set `user_id`. Consumer-key class = `role=agent` + non-empty `project_ids` + `allow_project_override=false`.

**Tech Stack:** Go (stdlib net/http, database/sql, golang-migrate), PostgreSQL. Spec: `docs/superpowers/specs/2026-06-25-daab-consumer-key-user-scope-design.md`.

## Global Constraints

- **D7 (directive):** resolve `user_id` **từ key**, KHÔNG nhận làm tool-arg.
- **Precedence:** key có `user_id` → user-scope; `NULL` → project-scope (P0, KHÔNG regression).
- **Store KHÔNG đổi:** `AgentContextUpsert.UserID` (store:15, "empty→NULL"), `AgentRecallParams.UserID` (store:133, "empty→no filter"), filter `AND a.user_id` (store:165) đã có sẵn.
- Test: `go test -race`, table-driven. DB store tests = `package store_test` + `setupTestDB(t)` (skip nếu thiếu `KG_TEST_DATABASE_URL`). Handler tests = `package handler`.
- Migration phải có `.up.sql` + `.down.sql`. Latest hiện tại = `000069` → mới = **`000070`**.
- Nested git repo: commit qua `git -C ennam.kg.go`.
- Consumer-key class chỉ áp policy khi **phát hành consumer key**; KHÔNG phá model admin-all hợp lệ.

---

## File Structure

- `db/migrations/000070_add_api_key_user_id.{up,down}.sql` — cột `api_keys.user_id`.
- `internal/models/apikey.go` (modify) — field `UserID *string`.
- `internal/store/apikey.go` (modify) — thêm `user_id` vào INSERT + mọi SELECT column-list + Scan.
- `internal/middleware/auth.go` (modify) — `DeveloperIdentity.UserID` + gán khi build identity.
- `internal/handler/agent_context.go` (modify) — `resolveWriteIdentity` trả user_id; Remember + Recall truyền `UserID`.
- `internal/service/apikey.go` (modify) — `CreateKeyRequest.UserID` → set vào `models.APIKey.UserID`.
- `internal/service/user.go` (modify) — `LoginWithSupabase`/`CreateUser` set `CreateKeyRequest.UserID`.
- `internal/handler/apikey_mgmt.go` (modify) — `apiKeyCreateReq.UserID` (optional, "for user").
- `internal/handler/auth.go` (modify) — `/auth/supabase` consumer variant: label `consumer-session-*` + user_id.
- `internal/handler/recall_isolation_test.go` (modify) — T6/T7 user-isolation.

---

## Task 1: Migration + model + store cho `api_keys.user_id`

**Files:**
- Create: `db/migrations/000070_add_api_key_user_id.up.sql`, `.down.sql`
- Modify: `internal/models/apikey.go` (struct APIKey), `internal/store/apikey.go` (INSERT L38-41 + Scan L57; SELECT lists L99/115/130/142 + scans; Update RETURNING L161/210 + scans)
- Test: `internal/store/apikey_user_id_test.go`

**Interfaces:**
- Produces: `models.APIKey.UserID *string`; mọi đọc/ghi api_keys round-trip cột `user_id`.

- [ ] **Step 1: Write migration**

`db/migrations/000070_add_api_key_user_id.up.sql`:
```sql
-- D3/g2b: key carries its owning user (forward link → many keys per user,
-- unlike single-slot users.api_key_id). NULL = service/project-scoped key.
ALTER TABLE api_keys ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_api_keys_user_id ON api_keys (user_id) WHERE user_id IS NOT NULL;
```
`db/migrations/000070_add_api_key_user_id.down.sql`:
```sql
DROP INDEX IF EXISTS idx_api_keys_user_id;
ALTER TABLE api_keys DROP COLUMN IF EXISTS user_id;
```

- [ ] **Step 2: Add model field**

`internal/models/apikey.go` — thêm vào struct `APIKey` (sau `AllowProjectOverride`):
```go
	// UserID links this key to a user account (memory user-scope). Nil = service/project key.
	UserID *string `json:"user_id,omitempty" db:"user_id"`
```

- [ ] **Step 3: Thread `user_id` through store apikey.go**

Trong `internal/store/apikey.go`, thêm `user_id` vào MỌI chỗ đọc/ghi (giữ thứ tự cột nhất quán — append `user_id` sau `allow_project_override`):
- **Create INSERT (L38-41):** thêm cột `user_id` vào danh sách INSERT + thêm `$9` value (`key.UserID`) + thêm `user_id` vào `RETURNING`.
- **Mọi SELECT column-list (L99, L115, L130, L142) và Update RETURNING (L161, L210):** thêm `, user_id` cuối list.
- **Mọi `.Scan(...)` tương ứng (Create L57, single-row scans, list scan L289):** thêm `&userID` (kiểu `sql.NullString`) cuối, rồi map: `if userID.Valid { key.UserID = &userID.String }`.

Mẫu cho 1 site scan — ⚠️ KHỚP PATTERN THẬT (verified store/apikey.go:57-70): `ProjectIDs` dùng `pq.Array`, các cột nullable dùng biến `sql.NullString`/`sql.NullTime` cục bộ rồi map. Thêm `userID sql.NullString` ở CUỐI:
```go
var defaultProjectID, userID sql.NullString
var revokedAt, lastUsedAt sql.NullTime
err := row.Scan(
	&result.ID, &result.KeyHash, &result.KeyPrefix, &result.Label, &result.DeveloperName,
	&result.Role, pq.Array(&result.ProjectIDs), &defaultProjectID, &result.AllowProjectOverride,
	&result.CreatedAt, &revokedAt, &lastUsedAt, &userID, // <-- thêm &userID cuối
)
// ... mapping nullable hiện có giữ nguyên, thêm:
if userID.Valid { result.UserID = &userID.String }
```
> Quan trọng: (a) thứ tự cột RETURNING/SELECT phải khớp `.Scan`; append `user_id` ở CUỐI mọi list + scan. (b) Mỗi site có sẵn các biến `defaultProjectID/revokedAt/lastUsedAt` + mapping của nó — chỉ **thêm** `userID` vào, đừng đổi cái cũ. (c) `pq` đã được import sẵn trong file.

- [ ] **Step 4: Write the failing test (`package store_test`)**

`internal/store/apikey_user_id_test.go`:
```go
package store_test

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

func TestAPIKeyStore_UserIDRoundTrip(t *testing.T) {
	db := setupTestDB(t) // skips if KG_TEST_DATABASE_URL unset
	s := store.NewAPIKeyStore(db)
	ctx := context.Background()

	// Seed a user to satisfy the FK.
	var uid string
	if err := db.QueryRowContext(ctx,
		`INSERT INTO users (username, display_name, role, status) VALUES ($1,$1,'viewer','active') RETURNING id`,
		"apikey-uid-test").Scan(&uid); err != nil {
		t.Fatalf("seed user: %v", err)
	}
	t.Cleanup(func() { _, _ = db.ExecContext(ctx, "DELETE FROM users WHERE id=$1", uid) })

	created, err := s.Create(ctx, &models.APIKey{
		KeyHash: "h1", KeyPrefix: "pfx12345", Label: "ck", DeveloperName: "svc",
		Role: models.APIKeyRoleAgent, ProjectIDs: []string{}, UserID: &uid,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if created.UserID == nil || *created.UserID != uid {
		t.Fatalf("UserID not round-tripped on create: %v", created.UserID)
	}
	got, err := s.GetByID(ctx, created.ID)
	if err != nil || got.UserID == nil || *got.UserID != uid {
		t.Fatalf("UserID not round-tripped on get: err=%v got=%v", err, got.UserID)
	}
}
```
> Dùng đúng API store sẵn có. Nếu `Create`/`GetByID` tên khác trong apikey.go, đọc file trước rồi khớp tên.

- [ ] **Step 5: Run migration + test**

```bash
cd ennam.kg.go && make db-migrate && \
  KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5432/ennam_kg?sslmode=disable" \
  go test ./internal/store/ -run TestAPIKeyStore_UserIDRoundTrip -v
```
Expected: PASS (cần Postgres dev + migration 000070). `go build ./...` clean.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add db/migrations/000070_add_api_key_user_id.up.sql db/migrations/000070_add_api_key_user_id.down.sql internal/models/apikey.go internal/store/apikey.go internal/store/apikey_user_id_test.go
git -C ennam.kg.go commit -m "feat(auth): add api_keys.user_id column + store round-trip"
```

---

## Task 2: Carry `user_id` vào DeveloperIdentity

**Files:**
- Modify: `internal/middleware/auth.go` (struct `DeveloperIdentity` ~L44; build site L203-211)
- Test: `internal/middleware/auth_test.go`

**Interfaces:**
- Consumes: `models.APIKey.UserID` (Task 1).
- Produces: `DeveloperIdentity.UserID string` (empty nếu key không gắn user).

- [ ] **Step 1: Write the failing test**

Thêm vào `internal/middleware/auth_test.go`:
```go
func TestDeveloperIdentity_CarriesUserID(t *testing.T) {
	uid := "11111111-1111-1111-1111-111111111111"
	key := &models.APIKey{ID: "k1", DeveloperName: "svc", Role: models.APIKeyRoleAgent, UserID: &uid}
	id := developerIdentityFromKey(key) // helper extracted in Step 3
	if id.UserID != uid {
		t.Errorf("want UserID %s, got %q", uid, id.UserID)
	}
	key2 := &models.APIKey{ID: "k2", DeveloperName: "svc", Role: models.APIKeyRoleAdmin}
	if got := developerIdentityFromKey(key2).UserID; got != "" {
		t.Errorf("want empty UserID for keyless, got %q", got)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ennam.kg.go && go test ./internal/middleware/ -run TestDeveloperIdentity_CarriesUserID -v
```
Expected: FAIL (`developerIdentityFromKey` undefined / no UserID field).

- [ ] **Step 3: Implement**

`internal/middleware/auth.go` — thêm field vào struct `DeveloperIdentity`:
```go
	// UserID is the user account this key belongs to (empty for service/project keys).
	UserID string
```
Trích build-logic (L203-211) thành helper + dùng lại:
```go
func developerIdentityFromKey(key *models.APIKey) *DeveloperIdentity {
	uid := ""
	if key.UserID != nil {
		uid = *key.UserID
	}
	return &DeveloperIdentity{
		KeyID:                key.ID,
		DeveloperName:        key.DeveloperName,
		Role:                 key.Role,
		ProjectIDs:           key.ProjectIDs,
		DefaultProjectID:     key.DefaultProjectID,
		AllowProjectOverride: key.AllowProjectOverride,
		KeyPrefix:            key.KeyPrefix,
		UserID:               uid,
	}
}
```
Thay block `identity := &DeveloperIdentity{...}` (L203-211) bằng `identity := developerIdentityFromKey(key)`.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ennam.kg.go && go test ./internal/middleware/ -race -run TestDeveloperIdentity -v && go build ./...
```
Expected: PASS + build clean.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/middleware/auth.go internal/middleware/auth_test.go
git -C ennam.kg.go commit -m "feat(auth): carry api key user_id into DeveloperIdentity"
```

---

## Task 3: Wire `kg_remember`/`kg_recall` to user_id (g2b LIVE)

**Files:**
- Modify: `internal/handler/agent_context.go` (`resolveWriteIdentity` L194-205; `Remember` upsert call L106; `Recall` params L174)
- Test: `internal/handler/agent_context_userscope_test.go`

**Interfaces:**
- Consumes: `DeveloperIdentity.UserID` (Task 2); `store.AgentContextUpsert.UserID`, `store.AgentRecallParams.UserID` (đã có).
- Produces: write set `user_id`; recall filter theo `user_id`.

- [ ] **Step 1: Implement handler wiring**

`internal/handler/agent_context.go`:
- Đổi `resolveWriteIdentity` trả thêm user_id (signature `(projectID, sourceAgent, userID string, ok bool)`):
```go
func (h *AgentContextHandler) resolveWriteIdentity(w http.ResponseWriter, r *http.Request) (string, string, string, bool) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil {
		return "", "unknown", "", true
	}
	pid, ok := identity.ResolveProjectID("")
	if !ok {
		errorResponse(w, http.StatusBadRequest, "no project context for this key")
		return "", "", "", false
	}
	return pid, identity.DeveloperName, identity.UserID, true
}
```
- `Remember`: cập caller + set `UserID` trong upsert:
```go
	projectID, sourceAgent, userID, ok := h.resolveWriteIdentity(w, r)
	if !ok {
		return
	}
	// ... (validation giữ nguyên) ...
	id, created, err := h.store.UpsertAgentContext(r.Context(), store.AgentContextUpsert{
		ProjectID:   projectID,
		UserID:      userID,
		SourceAgent: sourceAgent,
		Kind:        body.Kind,
		Scope:       body.Scope,
		MemKey:      body.MemKey,
		Content:     body.Content,
		Tags:        body.Tags,
	})
```
- `Recall`: resolve userID từ identity + truyền vào params:
```go
	identity := middleware.GetDeveloperIdentity(r.Context())
	projectID := ""
	userID := ""
	if identity != nil {
		pid, ok := identity.ResolveProjectID("")
		if !ok {
			writeJSON(w, http.StatusOK, map[string]interface{}{"results": []recallView{}})
			return
		}
		projectID = pid
		userID = identity.UserID
	}
	// ...
	rows, err := h.store.RecallAgentContext(r.Context(), store.AgentRecallParams{
		ProjectID:      projectID,
		UserID:         userID,
		QueryEmbedding: qvec,
		Query:          body.Query,
		Kind:           body.Kind,
		Scope:          body.Scope,
		Tags:           body.Tags,
		TopK:           body.TopK,
	})
```

- [ ] **Step 2: Write the test (`package handler`, DB-backed)**

`internal/handler/agent_context_userscope_test.go`:
```go
package handler

// Verifies user-scope: a key with UserID set writes + recalls only that user's
// memory; a different user's key cannot recall it; a key with no UserID is
// project-scoped (P0 unchanged).
//
// Run with KG_TEST_DATABASE_URL set (skips otherwise) — mirror the DB setup
// helper used by recall_isolation_integration_test.go in this package.
```
> Viết test theo helper DB sẵn có trong package handler (xem `recall_isolation_integration_test.go`): seed 1 project + 2 user-scoped key (userA, userB) cùng project; `Remember` qua key A; `Recall` qua key A thấy, qua key B KHÔNG thấy; key project-only (UserID="") thấy theo project. Dùng `httptest` + inject `DeveloperIdentity{UserID:...}` vào context như các test khác trong package.

- [ ] **Step 3: Run test + build**

```bash
cd ennam.kg.go && go build ./... && \
  KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5432/ennam_kg?sslmode=disable" \
  go test ./internal/handler/ -race -run "UserScope|Recall|Remember" -v
```
Expected: PASS (user A isolated from user B; project-only unchanged).

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.go add internal/handler/agent_context.go internal/handler/agent_context_userscope_test.go
git -C ennam.kg.go commit -m "feat(memory): wire user_id scoping into kg_remember/kg_recall (g2b live)"
```

---

## Task 4: Set `user_id` khi login/JIT mint key

**Files:**
- Modify: `internal/service/apikey.go` (`CreateKeyRequest` + build `models.APIKey` L125-131), `internal/service/user.go` (`LoginWithSupabase`, `CreateUser`, `Login` CreateKey calls)
- Test: `internal/service/user_supabase_test.go` (mở rộng)

**Interfaces:**
- Consumes: `models.APIKey.UserID` (Task 1).
- Produces: `CreateKeyRequest.UserID *string` → key mint mang user_id.

- [ ] **Step 1: Add `UserID` to CreateKeyRequest + build**

`internal/service/apikey.go`:
```go
	// UserID links the minted key to a user account (memory user-scope). Optional.
	UserID *string `json:"-"`
```
(thêm vào `CreateKeyRequest`). Trong build `key := &models.APIKey{...}` (L125-131) thêm:
```go
		UserID: req.UserID,
```

- [ ] **Step 2: Set UserID ở các CreateKey nội bộ**

`internal/service/user.go` — trong `CreateUser` (L98 CreateKey), `Login` (L375), `LoginWithSupabase` (mint key) + `EnableUser` (L202): thêm `UserID: &created.ID` / `UserID: &user.ID` vào `CreateKeyRequest{...}` để key gắn user. (Với `CreateUser`, sau khi có `created.ID`; nếu key mint trước user-insert như hiện tại, set `api_key.user_id` qua 1 UPDATE sau khi tạo user, hoặc đổi thứ tự — đọc thứ tự hiện tại trước khi sửa.)
> **Lưu ý thứ tự (CreateUser):** hiện key mint TRƯỚC khi insert user (L98 → L120). Nên user_id chưa biết lúc mint. Giải pháp tối thiểu: sau khi `created` có ID, gọi store cập `api_keys.user_id = created.ID` cho `keyResp.Key.ID` (thêm `APIKeyStore.SetUserID(ctx, keyID, userID)` nhỏ). Hoặc `LoginWithSupabase`/`Login` (user đã tồn tại) set thẳng `UserID: &user.ID` trong CreateKeyRequest.

- [ ] **Step 3: (nếu cần) thêm store `SetUserID`**

`internal/store/apikey.go`:
```go
func (s *APIKeyStore) SetUserID(ctx context.Context, keyID, userID string) error {
	_, err := s.db.ExecContext(ctx, `UPDATE api_keys SET user_id=$2 WHERE id=$1`, keyID, userID)
	if err != nil {
		return fmt.Errorf("set api key user_id: %w", err)
	}
	return nil
}
```

- [ ] **Step 4: Write/extend test**

Mở rộng `internal/service/user_supabase_test.go` (fake repo + keySvc): sau `LoginWithSupabase`, assert `CreateKeyRequest` mà keySvc nhận có `UserID != nil` = user.ID. (Cho fake keySvc lưu lại req cuối; assert req.UserID.)
```go
func TestLoginWithSupabase_MintsUserScopedKey(t *testing.T) {
	repo := newFakeUserRepo()
	keys := newFakeKeySvc() // capture last CreateKeyRequest
	svc := NewUserService(repo, keys, nil)
	resp, err := svc.LoginWithSupabase(context.Background(), "sub-x", "x@exnodes.vn", map[string]bool{})
	if err != nil { t.Fatalf("err: %v", err) }
	if keys.lastCreate.UserID == nil || *keys.lastCreate.UserID != resp.User.ID {
		t.Errorf("minted key not bound to user: %v", keys.lastCreate.UserID)
	}
}
```

- [ ] **Step 5: Run + build**

```bash
cd ennam.kg.go && go build ./... && go test ./internal/service/ -race -run "LoginWithSupabase|CreateUser" -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/service/apikey.go internal/service/user.go internal/store/apikey.go internal/service/user_supabase_test.go
git -C ennam.kg.go commit -m "feat(auth): login/JIT keys carry user_id"
```

---

## Task 5: Dashboard "for user" + consumer token-exchange key

**Files:**
- Modify: `internal/handler/apikey_mgmt.go` (`apiKeyCreateReq` L27-32 + CreateKey call L73), `internal/handler/auth.go` (`SupabaseLogin` consumer variant)
- Test: `internal/handler/apikey_mgmt_test.go`, `internal/handler/auth_supabase_test.go`

**Interfaces:**
- Consumes: `service.CreateKeyRequest.UserID` (Task 4).
- Produces: dashboard create key optional `user_id`; `/auth/supabase?session=consumer` → key label `consumer-session-*` + user_id.

- [ ] **Step 1: Dashboard optional user_id**

`internal/handler/apikey_mgmt.go` — thêm vào `apiKeyCreateReq`:
```go
	UserID *string `json:"user_id,omitempty"`
```
Trong CreateKey (L73) truyền `UserID: req.UserID` vào `service.CreateKeyRequest{...}`.

- [ ] **Step 2: Consumer token-exchange variant**

`internal/handler/auth.go` `SupabaseLogin`: nếu query `session=consumer` (hoặc header `X-KG-Client: consumer`) → gọi 1 đường mint **không revoke web-session** + label `consumer-session-*` + set user_id. Tối thiểu: thêm `UserService.LoginWithSupabaseConsumer(ctx, sub, email, adminEmails)` y hệt `LoginWithSupabase` nhưng (a) label `consumer-session-<username>`, (b) KHÔNG revoke/đụng `web-session-*` của user, (c) KHÔNG ghi đè `users.api_key_id` (để không phá phiên dashboard của user), (d) `CreateKeyRequest.UserID=&user.ID`.
```go
// trong SupabaseLogin, sau verify + claims:
if r.URL.Query().Get("session") == "consumer" {
	resp, err = h.userService.LoginWithSupabaseConsumer(ctx, claims.Sub, claims.Email, h.adminEmails)
} else {
	resp, err = h.userService.LoginWithSupabase(ctx, claims.Sub, claims.Email, h.adminEmails)
}
```

- [ ] **Step 3: Write tests**

`apikey_mgmt_test.go`: POST create key với `user_id` → service nhận `CreateKeyRequest.UserID` đúng (fake service capture).
`auth_supabase_test.go`: `SupabaseLogin` với `?session=consumer` (fake verifier + fake service) → gọi `LoginWithSupabaseConsumer` (fake userService ghi cờ); không có query → gọi `LoginWithSupabase`.
```go
func TestSupabaseLogin_ConsumerVariant(t *testing.T) {
	us := &fakeUserSvc{} // implements the methods SupabaseLogin calls
	h := &AuthHandler{verifier: fakeVerifier{claims: &supabaseauth.Claims{Sub: "s", Email: "a@x.vn"}}, userService: us, logger: slog.Default()}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/supabase?session=consumer", strings.NewReader(`{"access_token":"t"}`))
	h.SupabaseLogin(httptest.NewRecorder(), req)
	if !us.consumerCalled {
		t.Error("expected LoginWithSupabaseConsumer for session=consumer")
	}
}
```
> Nếu `AuthHandler.userService` là `*service.UserService` cụ thể (không phải interface), refactor nhẹ sang interface nhỏ để test inject — hoặc test ở tầng service. Đọc auth.go trước khi chọn.

- [ ] **Step 4: Run + build**

```bash
cd ennam.kg.go && go build ./... && go test ./internal/handler/ -race -run "APIKey|SupabaseLogin" -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/handler/apikey_mgmt.go internal/handler/auth.go internal/service/user.go internal/handler/apikey_mgmt_test.go internal/handler/auth_supabase_test.go
git -C ennam.kg.go commit -m "feat(auth): dashboard for-user keys + consumer token-exchange (consumer-session label)"
```

---

## Task 6: Consumer-key class policy

**Files:**
- Modify: `internal/service/apikey.go` (`validateCreateKey` / CreateKey validation ~L337)
- Test: `internal/service/apikey_test.go`

**Interfaces:**
- Consumes: `CreateKeyRequest` (Role, ProjectIDs).
- Produces: validation từ chối consumer-key cấu hình nguy hiểm.

- [ ] **Step 1: Write the failing test**

`internal/service/apikey_test.go`:
```go
func TestCreateKey_ConsumerPolicy(t *testing.T) {
	// A consumer key (role=agent, non-internal) MUST have non-empty project_ids.
	svc := NewAPIKeyService(newFakeAPIKeyRepo(), nil)
	_, err := svc.CreateKey(context.Background(), CreateKeyRequest{
		DeveloperName: "aaaa", Role: models.APIKeyRoleAgent, ProjectIDs: []string{},
	})
	if err == nil {
		t.Error("expected error: agent key with empty project_ids (consumer must be project-scoped)")
	}
	// With a project → allowed.
	if _, err := svc.CreateKey(context.Background(), CreateKeyRequest{
		DeveloperName: "aaaa", Role: models.APIKeyRoleAgent, ProjectIDs: []string{"p1"},
	}); err != nil {
		t.Errorf("agent key with project should pass: %v", err)
	}
}
```
> Lưu ý: validation hiện tại (L337) đã yêu cầu non-admin + empty project_ids + !Internal → lỗi. Test này có thể đã PASS một phần — xác nhận `role=agent` rơi vào nhánh đó. Nếu đã đủ, Task 6 chỉ là **thêm test khẳng định** + (nếu cần) siết riêng cho consumer. KHÔNG nới lỏng admin-all.

- [ ] **Step 2: Run → implement nếu fail**

```bash
cd ennam.kg.go && go test ./internal/service/ -run TestCreateKey_ConsumerPolicy -v
```
Nếu FAIL: siết validation trong CreateKey — agent role + empty project_ids + !Internal → trả `ValidationError{Field:"project_ids", Message:"consumer (agent) key must be scoped to at least one project"}`. (Giữ nguyên nhánh admin/Internal.)

- [ ] **Step 3: Run + build**

```bash
cd ennam.kg.go && go test ./internal/service/ -race -run TestCreateKey -v && go build ./...
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.go add internal/service/apikey.go internal/service/apikey_test.go
git -C ennam.kg.go commit -m "feat(auth): consumer-key policy (agent key requires project scope)"
```

---

## Task 7: T6/T7 user-isolation + full verify

**Files:**
- Modify: `internal/handler/recall_isolation_test.go` (thêm T6/T7)

**Interfaces:** Consumes mọi thứ Task 1-3.

- [ ] **Step 1: Add T6/T7 (mirror file's existing pattern)**

`internal/handler/recall_isolation_test.go` — thêm 2 test theo đúng pattern các test sẵn có (Auth→ProjectID→handler chain, seed 2 key/identity):
```go
// T6: recall scoped by user — user A's key must NOT return user B's memory in the same project.
func TestRecall_UserScopeIsolation(t *testing.T) {
	// seed project P; identity keyA{UserID:A,project:P}, keyB{UserID:B,project:P}
	// Remember via keyA (content "secret-A"); Recall via keyB → must NOT contain "secret-A".
	// Recall via keyA → contains "secret-A".
}

// T7: a project-only key (UserID="") sees project-scoped memory (P0 unchanged, no regression).
func TestRecall_ProjectOnlyKeyUnchanged(t *testing.T) {
	// Remember via project-only key; Recall via same project-only key → sees it.
}
```
> Viết đầy đủ theo helper/seed có sẵn trong file (gắn `DeveloperIdentity{UserID:...}` vào request context như các T1-T5). Nếu cần DB, đặt ở `recall_isolation_integration_test.go` (build-tag/`setupTestDB`).

- [ ] **Step 2: Run full gate suite**

```bash
cd ennam.kg.go && go build ./... && go test ./internal/... -race -run "Isolation|UserScope|Recall|Remember|CreateKey|SupabaseLogin|DeveloperIdentity|APIKey" -v
```
Expected: tất cả PASS. (DB-backed test skip nếu không set `KG_TEST_DATABASE_URL`.)

- [ ] **Step 3: Security review**

Dispatch `security-reviewer` agent trên: `api_keys.user_id` flow, `agent_context.go` user-scope wiring, consumer token-exchange (`auth.go`), consumer-key policy. Address CRITICAL/HIGH.

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.go add internal/handler/recall_isolation_test.go
git -C ennam.kg.go commit -m "test(memory): T6/T7 user-scope isolation (gate g2b)"
```

---

## Self-Review (đã chạy)

- **Spec coverage:** §3.1 consumer-key → Task 6; §3.2 user_id live (migration+identity+handler+key-creation) → Task 1/2/3/4/5; §3.3 token-exchange consumer-session → Task 5; §3.4 T6/T7 → Task 7. ✓
- **Placeholder scan:** Task 3 Step 2 + Task 7 Step 1 mô tả test bằng prose + skeleton (không full code) — CÓ CHỦ Ý: chúng phải mirror DB-setup/seed helper sẵn có trong package (`recall_isolation_integration_test.go`); chỉ rõ seed/assert cần gì. Mọi step code khác có nội dung thật.
- **Type consistency:** `models.APIKey.UserID *string` → `DeveloperIdentity.UserID string` (deref, "" nếu nil) → `AgentContextUpsert.UserID`/`AgentRecallParams.UserID string` (đã có) → `CreateKeyRequest.UserID *string`. Nhất quán (pointer ở model/request, string ở identity/store-params). ✓
- **Store KHÔNG đổi cho user_id memory path** (chỉ apikey store thêm cột) — đúng spec.

## Open dependencies cần xác nhận khi execute
- Thứ tự mint-key vs user-insert trong `CreateUser` (Task 4 Step 2) — đọc trước; có thể cần `SetUserID` (Step 3).
- `AuthHandler.userService` là struct cụ thể hay interface (Task 5 test inject) — đọc auth.go.
- apikey store có nhiều inline SELECT/scan (L99/115/130/142/161/210) — Task 1 phải sửa HẾT cho nhất quán cột.
- Tên helper DB-setup trong `internal/handler` (cho Task 3/7 DB tests) — mirror `recall_isolation_integration_test.go`.
