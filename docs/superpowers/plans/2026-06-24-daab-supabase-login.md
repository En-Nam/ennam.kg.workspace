# DAAB → Supabase Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép user đăng nhập DAAB bằng identity Supabase (verify JWT qua JWKS ES256, JIT-provision role viewer, mint internal api-key như cũ), giữ login username/password legacy song song (coexist).

**Architecture:** FE login Supabase (supabase-js) → access_token → `POST /api/v1/auth/supabase` → Go verify chữ ký ES256 bằng JWKS public key (không secret) → JIT user (status active, role viewer / admin nếu allowlist) → mint `web-session-*` api-key (đúng pattern `UserService.Login`) → iron-session. MCP/agent auth không đổi.

**Tech Stack:** Go (stdlib net/http, database/sql, `lestrrat-go/jwx/v2`), PostgreSQL (golang-migrate), Next.js 16 / React 19, `@supabase/supabase-js`, iron-session.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-24-daab-supabase-login-design.md` (PRE-BUILD GATE đã ĐÓNG — token thật ký ES256, signature valid).
- Supabase project: `SUPABASE_URL=https://nicrcubktflnwdkhotut.supabase.co`; JWKS = `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`; expected `iss=${SUPABASE_URL}/auth/v1`; `aud=authenticated`; key `alg=ES256`, `kid=2dbb07a3-c643-4821-b608-ce016cc7e5a2`.
- Chỉ chấp nhận `ES256` từ JWKS — từ chối `alg=none`/HS*. Verify đủ: chữ ký, `exp`, `iss`, `aud`.
- JIT mặc định `role=viewer`, `status=active` (KHÔNG `pending_password_change`), `password_hash=NULL`. **Không** auto-gán project.
- **Không** dùng `UserService.CreateUser` cho JIT (nó bắt buộc password + set pending). Dùng path tạo riêng.
- Test: Go `go test -race`, table-driven. Migration phải có `.up.sql` + `.down.sql`.
- Nested git repo: commit trong `ennam.kg.go` và `ennam.kg.next` riêng (dùng `git -C`).
- User test sẵn có để integration: `dragoon@exnodes.vn` / `Dev123!@#` (Supabase sub `e7028d06-1f54-468e-837f-c58eb3258c7d`) — GIỮ, đừng xoá.

---

## File Structure

**ennam.kg.go (backend):**
- `db/migrations/000069_add_supabase_user_id.up.sql` / `.down.sql` — cột `supabase_user_id`.
- `internal/models/user.go` (modify) — thêm field `SupabaseUserID *string`.
- `internal/store/user.go` (modify) — `userColumns` + scan thêm cột; methods `GetBySupabaseID`, `CreateSupabaseUser`, `SetSupabaseID`.
- `internal/supabaseauth/verifier.go` (create) — `Verifier`, `Claims`, `KeySource`, `CachedKeySource`.
- `internal/supabaseauth/verifier_test.go` (create).
- `internal/service/user.go` (modify) — `LoginWithSupabase`.
- `internal/handler/auth.go` (modify) — route + handler `SupabaseLogin`, struct, deps.
- `internal/middleware/auth.go` (modify) — `isExemptPath` thêm case.
- `cmd/kg-server/main.go` (modify) — đọc env, dựng verifier, inject vào `NewAuthHandler`.
- `go.mod` / `go.sum` — thêm `github.com/lestrrat-go/jwx/v2`.

**ennam.kg.next (frontend):**
- `src/lib/supabase/client.ts` (create) — browser supabase client.
- `src/app/(auth)/login/actions.ts` (modify) — `supabaseLoginAction`.
- `src/app/(auth)/login/page.tsx` (modify) — 2 tab (Email Supabase / Admin legacy).
- `.env.local.example` (modify) — `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- `package.json` — `@supabase/supabase-js`.

---

## Task 1: Migration + model + store cho `supabase_user_id`

**Files:**
- Create: `db/migrations/000069_add_supabase_user_id.up.sql`, `db/migrations/000069_add_supabase_user_id.down.sql`
- Modify: `internal/models/user.go` (struct User, sau dòng `UpdatedAt`), `internal/store/user.go` (`userColumns` :23, `scanOneRow` :251, `scanMany` Scan :323)
- Test: `internal/store/user_test.go`

**Interfaces:**
- Produces (trên `*store.UserStore` **và** thêm vào `service.UserRepository` interface — service gọi qua `s.repo`):
  - `models.User.SupabaseUserID *string`
  - `GetBySupabaseID(ctx, sub string) (*models.User, error)` — trả `(nil, nil)` nếu không có.
  - `GetByEmail(ctx, email string) (*models.User, error)` — trả `(nil, nil)` nếu không có (dùng cho link OQ-3).
  - `CreateSupabaseUser(ctx, u *models.User) (*models.User, error)` — INSERT có `supabase_user_id`, `password_hash` NULL.
  - `SetSupabaseID(ctx, userID, sub string) (*models.User, error)` — link sub vào user có sẵn.
- **Verified:** `UserRepository` đã có `UpdateLoginSuccess`, `UpdateAPIKeyID`; `UserAPIKeyService` đã có `GetKey/RevokeKey/CreateKey` — KHÔNG cần thêm. Chỉ thêm 4 method trên.

- [ ] **Step 1: Write migration files**

`db/migrations/000069_add_supabase_user_id.up.sql`:
```sql
-- Supabase identity link (BA — DAAB→Supabase login). Nullable: legacy users keep NULL.
ALTER TABLE users ADD COLUMN supabase_user_id UUID;
CREATE UNIQUE INDEX idx_users_supabase_user_id
    ON users (supabase_user_id) WHERE supabase_user_id IS NOT NULL;
```

`db/migrations/000069_add_supabase_user_id.down.sql`:
```sql
DROP INDEX IF EXISTS idx_users_supabase_user_id;
ALTER TABLE users DROP COLUMN IF EXISTS supabase_user_id;
```

- [ ] **Step 2: Add model field**

Trong `internal/models/user.go`, thêm vào struct `User` ngay sau `UpdatedAt`:
```go
	SupabaseUserID   *string    `json:"supabase_user_id,omitempty" db:"supabase_user_id"`
```

- [ ] **Step 3: Update store column list + scan**

`internal/store/user.go` — `userColumns` (:23) thêm cột cuối:
```go
const userColumns = `id, username, email, password_hash, display_name, role, status,
	api_key_id, last_login_at, failed_login_count, locked_at,
	created_by, created_at, updated_at, supabase_user_id`
```

Trong `scanOneRow` (:251), thêm biến + dòng Scan cuối + gán:
```go
	var supabaseUserID sql.NullString
```
(thêm cùng nhóm `var ... sql.NullString` phía trên `Scan`)
```go
		&u.UpdatedAt,
		&supabaseUserID,
	)
```
(thêm `&supabaseUserID` ngay sau `&u.UpdatedAt`)
```go
	if supabaseUserID.Valid {
		u.SupabaseUserID = &supabaseUserID.String
	}
```
(thêm vào cụm gán sau `Scan`)

Trong `scanMany` (:323 `rows.Scan(`), thêm cùng kiểu: khai báo `var supabaseUserID sql.NullString` trong vòng lặp, thêm `&supabaseUserID` sau `&u.UpdatedAt`, và gán `if supabaseUserID.Valid { u.SupabaseUserID = &supabaseUserID.String }`.

- [ ] **Step 4: Add store methods**

Thêm vào `internal/store/user.go` (sau `GetByAPIKeyID`):
```go
// GetBySupabaseID retrieves a user by their linked Supabase user id.
// Returns nil, nil if no user is linked (caller decides to JIT-create).
func (s *UserStore) GetBySupabaseID(ctx context.Context, sub string) (*models.User, error) {
	if sub == "" {
		return nil, fmt.Errorf("supabase id is required")
	}
	query := `SELECT ` + userColumns + ` FROM users WHERE supabase_user_id = $1`
	u, err := s.scanOneRow(ctx, query, sub)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("get user by supabase id: %w", err)
	}
	return u, nil
}

// CreateSupabaseUser inserts a Supabase-provisioned user (no password).
func (s *UserStore) CreateSupabaseUser(ctx context.Context, user *models.User) (*models.User, error) {
	query := `
		INSERT INTO users (username, email, display_name, role, status, api_key_id, supabase_user_id)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		RETURNING ` + userColumns
	return s.scanOne(ctx, query,
		user.Username,
		user.Email,
		user.DisplayName,
		string(user.Role),
		string(user.Status),
		user.APIKeyID,
		user.SupabaseUserID,
	)
}

// SetSupabaseID links an existing user to a Supabase identity.
func (s *UserStore) SetSupabaseID(ctx context.Context, userID, sub string) (*models.User, error) {
	query := `UPDATE users SET supabase_user_id = $2 WHERE id = $1 RETURNING ` + userColumns
	u, err := s.scanOneRow(ctx, query, userID, sub)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("user not found: %s", userID)
		}
		return nil, fmt.Errorf("set supabase id: %w", err)
	}
	return u, nil
}

// GetByEmail retrieves a user by email. Returns nil, nil if none (for JIT link).
func (s *UserStore) GetByEmail(ctx context.Context, email string) (*models.User, error) {
	if email == "" {
		return nil, fmt.Errorf("email is required")
	}
	query := `SELECT ` + userColumns + ` FROM users WHERE email = $1`
	u, err := s.scanOneRow(ctx, query, email)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("get user by email: %w", err)
	}
	return u, nil
}
```

Thêm 4 signature vào `service.UserRepository` interface (đầu `internal/service/user.go`):
```go
	GetBySupabaseID(ctx context.Context, sub string) (*models.User, error)
	GetByEmail(ctx context.Context, email string) (*models.User, error)
	CreateSupabaseUser(ctx context.Context, user *models.User) (*models.User, error)
	SetSupabaseID(ctx context.Context, userID, sub string) (*models.User, error)
```

- [ ] **Step 5: Write the failing test (DB-backed, `package store_test`)**

> **Verified:** DB store tests dùng `setupTestDB(t)` (định nghĩa trong `favorite_test.go`, **`package store_test`**) → **skip** nếu thiếu `KG_TEST_DATABASE_URL`. `user_test.go` là `package store` (chỉ test validation, không DB). Test mới PHẢI ở `package store_test`.

Tạo `internal/store/user_supabase_test.go`:
```go
package store_test

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

func strptr(s string) *string { return &s }

func TestUserStore_SupabaseRoundTrip(t *testing.T) {
	db := setupTestDB(t) // skips if KG_TEST_DATABASE_URL unset
	s := store.NewUserStore(db)
	ctx := context.Background()

	email := "sb-test@exnodes.vn"
	created, err := s.CreateSupabaseUser(ctx, &models.User{
		Username:       email,
		Email:          &email,
		DisplayName:    email,
		Role:           models.UserRoleViewer,
		Status:         models.UserStatusActive,
		SupabaseUserID: strptr("11111111-1111-1111-1111-111111111111"),
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	t.Cleanup(func() { _, _ = db.ExecContext(ctx, "DELETE FROM users WHERE id=$1", created.ID) })

	if created.PasswordHash != nil {
		t.Errorf("expected nil password_hash, got %v", *created.PasswordHash)
	}
	got, err := s.GetBySupabaseID(ctx, "11111111-1111-1111-1111-111111111111")
	if err != nil || got == nil {
		t.Fatalf("get by supabase id: err=%v got=%v", err, got)
	}
	if got.ID != created.ID {
		t.Errorf("id mismatch: %s != %s", got.ID, created.ID)
	}
	miss, err := s.GetBySupabaseID(ctx, "00000000-0000-0000-0000-000000000000")
	if err != nil || miss != nil {
		t.Errorf("expected (nil,nil) for unknown sub, got (%v,%v)", miss, err)
	}
}
```

- [ ] **Step 6: Run migration + test**

```bash
cd ennam.kg.go && make db-migrate && \
  KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5432/ennam_kg?sslmode=disable" \
  go test ./internal/store/ -run TestUserStore_SupabaseRoundTrip -v
```
Expected: PASS (cần Postgres dev chạy + migration 000069 đã apply; nếu không set env → test SKIP, không phải fail). Trước khi sửa code: compile-fail (method chưa có).

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add db/migrations/000069_add_supabase_user_id.up.sql db/migrations/000069_add_supabase_user_id.down.sql internal/models/user.go internal/store/user.go internal/store/user_test.go
git -C ennam.kg.go commit -m "feat(auth): add supabase_user_id column + store methods"
```

---

## Task 2: Supabase JWT verifier (JWKS ES256)

**Files:**
- Create: `internal/supabaseauth/verifier.go`, `internal/supabaseauth/verifier_test.go`
- Modify: `go.mod`, `go.sum`

**Interfaces:**
- Produces:
  - `type Claims struct { Sub string; Email string }`
  - `type KeySource interface { KeySet(ctx context.Context) (jwk.Set, error) }`
  - `func NewVerifier(keys KeySource, issuer, audience string) *Verifier`
  - `func (v *Verifier) Verify(ctx context.Context, raw string) (*Claims, error)`
  - `func NewCachedKeySource(ctx context.Context, jwksURL string) (*CachedKeySource, error)` (impl `KeySource`)

- [ ] **Step 1: Add dependency** — ⚠️ **BẮT BUỘC jwx v2** (code dưới là API v2)

```bash
cd ennam.kg.go && go get github.com/lestrrat-go/jwx/v2@v2.1.3
```
> **Verified qua context7 (2026-06-24):** jwx **v4** đổi API hoàn toàn (`jwa.ES256()` là HÀM, JWKS qua module `jwkfetch`+`httprc/v3` với `Lookup`, `jwk.Import`, `tok.Get(key,&dst)`, `tok.Subject()`→(string,error)). Code trong plan dùng **API v2**: `jwa.ES256` (HẰNG SỐ), `jwk.FromRaw`, `jwk.NewCache(ctx)`+`Register`+`Refresh`+`Get`, `tok.Get("email")`→(any,bool), `tok.Subject()`→string. **KHÔNG** dùng v3/v4 — import path phải là `.../jwx/v2/...`.
> Chưa có trong module cache → `go get` cần mạng. Nếu sandbox chặn, chạy bước này ở môi trường có network trước.

- [ ] **Step 2: Write the failing test**

`internal/supabaseauth/verifier_test.go`:
```go
package supabaseauth

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"testing"
	"time"

	"github.com/lestrrat-go/jwx/v2/jwa"
	"github.com/lestrrat-go/jwx/v2/jwk"
	"github.com/lestrrat-go/jwx/v2/jwt"
)

const (
	testIssuer = "https://example.supabase.co/auth/v1"
	testAud    = "authenticated"
)

type staticKeys struct{ set jwk.Set }

func (s staticKeys) KeySet(_ context.Context) (jwk.Set, error) { return s.set, nil }

func newKeyPair(t *testing.T) (jwk.Key, jwk.Set) {
	t.Helper()
	raw, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	priv, err := jwk.FromRaw(raw)
	if err != nil {
		t.Fatal(err)
	}
	_ = priv.Set(jwk.KeyIDKey, "test-kid")
	_ = priv.Set(jwk.AlgorithmKey, jwa.ES256)
	pub, err := priv.PublicKey()
	if err != nil {
		t.Fatal(err)
	}
	set := jwk.NewSet()
	_ = set.AddKey(pub)
	return priv, set
}

func sign(t *testing.T, priv jwk.Key, iss, aud, sub, email string, exp time.Time) string {
	t.Helper()
	tok, err := jwt.NewBuilder().
		Issuer(iss).Audience([]string{aud}).Subject(sub).
		Claim("email", email).Expiration(exp).IssuedAt(time.Now()).Build()
	if err != nil {
		t.Fatal(err)
	}
	signed, err := jwt.Sign(tok, jwt.WithKey(jwa.ES256, priv))
	if err != nil {
		t.Fatal(err)
	}
	return string(signed)
}

func TestVerify_Valid(t *testing.T) {
	priv, set := newKeyPair(t)
	v := NewVerifier(staticKeys{set}, testIssuer, testAud)
	raw := sign(t, priv, testIssuer, testAud, "user-1", "a@exnodes.vn", time.Now().Add(time.Hour))
	c, err := v.Verify(context.Background(), raw)
	if err != nil {
		t.Fatalf("expected valid, got %v", err)
	}
	if c.Sub != "user-1" || c.Email != "a@exnodes.vn" {
		t.Errorf("claims mismatch: %+v", c)
	}
}

func TestVerify_Rejects(t *testing.T) {
	priv, set := newKeyPair(t)
	other, _ := newKeyPair(t)
	v := NewVerifier(staticKeys{set}, testIssuer, testAud)
	cases := map[string]string{
		"expired":       sign(t, priv, testIssuer, testAud, "u", "a@x.vn", time.Now().Add(-time.Hour)),
		"wrong issuer":  sign(t, priv, "https://evil/auth/v1", testAud, "u", "a@x.vn", time.Now().Add(time.Hour)),
		"wrong aud":     sign(t, priv, testIssuer, "anon", "u", "a@x.vn", time.Now().Add(time.Hour)),
		"foreign key":   sign(t, other, testIssuer, testAud, "u", "a@x.vn", time.Now().Add(time.Hour)),
		"garbage":       "not.a.jwt",
	}
	for name, raw := range cases {
		if _, err := v.Verify(context.Background(), raw); err == nil {
			t.Errorf("%s: expected error, got nil", name)
		}
	}
}

func TestVerify_MissingEmail(t *testing.T) {
	priv, set := newKeyPair(t)
	v := NewVerifier(staticKeys{set}, testIssuer, testAud)
	raw := sign(t, priv, testIssuer, testAud, "u", "", time.Now().Add(time.Hour))
	if _, err := v.Verify(context.Background(), raw); err == nil {
		t.Error("expected error for empty email")
	}
}
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd ennam.kg.go && go test ./internal/supabaseauth/ -v
```
Expected: FAIL (package/symbols not defined).

- [ ] **Step 4: Write minimal implementation**

`internal/supabaseauth/verifier.go`:
```go
// Package supabaseauth verifies Supabase-issued JWTs via the project JWKS (ES256).
package supabaseauth

import (
	"context"
	"fmt"
	"time"

	"github.com/lestrrat-go/jwx/v2/jwk"
	"github.com/lestrrat-go/jwx/v2/jwt"
)

// Claims holds the verified Supabase identity.
type Claims struct {
	Sub   string
	Email string
}

// KeySource supplies the JWKS key set used for verification.
type KeySource interface {
	KeySet(ctx context.Context) (jwk.Set, error)
}

// Verifier verifies Supabase access tokens.
type Verifier struct {
	keys     KeySource
	issuer   string
	audience string
}

// NewVerifier creates a Verifier. issuer = "<SUPABASE_URL>/auth/v1", audience = "authenticated".
func NewVerifier(keys KeySource, issuer, audience string) *Verifier {
	return &Verifier{keys: keys, issuer: issuer, audience: audience}
}

// Verify checks signature, exp, iss, aud and returns the identity claims.
func (v *Verifier) Verify(ctx context.Context, raw string) (*Claims, error) {
	set, err := v.keys.KeySet(ctx)
	if err != nil {
		return nil, fmt.Errorf("jwks unavailable: %w", err)
	}
	tok, err := jwt.Parse([]byte(raw),
		jwt.WithKeySet(set),
		jwt.WithValidate(true),
		jwt.WithIssuer(v.issuer),
		jwt.WithAudience(v.audience),
		jwt.WithAcceptableSkew(30*time.Second),
	)
	if err != nil {
		return nil, fmt.Errorf("token verification failed: %w", err)
	}
	emailVal, _ := tok.Get("email")
	email, _ := emailVal.(string)
	if tok.Subject() == "" || email == "" {
		return nil, fmt.Errorf("token missing sub or email")
	}
	return &Claims{Sub: tok.Subject(), Email: email}, nil
}

// CachedKeySource fetches and caches the JWKS, auto-refreshing on key rotation.
type CachedKeySource struct {
	cache *jwk.Cache
	url   string
}

// NewCachedKeySource registers + warms the JWKS cache. Fails loud if unreachable.
func NewCachedKeySource(ctx context.Context, jwksURL string) (*CachedKeySource, error) {
	c := jwk.NewCache(ctx)
	if err := c.Register(jwksURL, jwk.WithMinRefreshInterval(15*time.Minute)); err != nil {
		return nil, fmt.Errorf("register jwks: %w", err)
	}
	if _, err := c.Refresh(ctx, jwksURL); err != nil {
		return nil, fmt.Errorf("warm jwks: %w", err)
	}
	return &CachedKeySource{cache: c, url: jwksURL}, nil
}

// KeySet returns the cached set (cache handles refresh/rotation).
func (s *CachedKeySource) KeySet(ctx context.Context) (jwk.Set, error) {
	return s.cache.Get(ctx, s.url)
}
```

- [ ] **Step 5: Run tests + tidy**

```bash
cd ennam.kg.go && go mod tidy && go test ./internal/supabaseauth/ -race -v
```
Expected: PASS (TestVerify_Valid, TestVerify_Rejects, TestVerify_MissingEmail).

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/supabaseauth/ go.mod go.sum
git -C ennam.kg.go commit -m "feat(auth): supabase JWT verifier (JWKS ES256)"
```

---

## Task 3: Service `LoginWithSupabase`

**Files:**
- Modify: `internal/service/user.go` (thêm method + helper allowlist)
- Test: `internal/service/user_supabase_test.go` (create)

**Interfaces:**
- Consumes: `(*store.UserStore).GetBySupabaseID/CreateSupabaseUser/SetSupabaseID` (Task 1); existing `s.repo` (UserRepository), `s.keySvc` (UserAPIKeyService).
- Produces: `(*UserService) LoginWithSupabase(ctx, sub, email string, adminEmails map[string]bool) (*LoginResponse, error)`

> **Note:** 4 method (`GetBySupabaseID`/`GetByEmail`/`CreateSupabaseUser`/`SetSupabaseID`) đã thêm vào interface ở Task 1. `UpdateLoginSuccess`/`UpdateAPIKeyID` (repo) + `GetKey`/`RevokeKey`/`CreateKey` (keySvc) **đã có sẵn** — verified.
> **Fake test:** tests ở `package service_test` (external) → fake `UserRepository` phải implement **TẤT CẢ** method của interface (13 cũ + 4 mới), đa số trả no-op/nil. Fake `UserAPIKeyService` implement `CreateKey`(trả `&CreateKeyResponse{Key:&models.APIKey{ID:"k"}, PlaintextKey:"k1"}`)/`RevokeKey`/`GetKey`. Kiểm `internal/service/apikey_test.go`/`user_test.go` xem đã có fake tái dùng được không trước khi tự viết.

- [ ] **Step 1: Write the failing test**

`internal/service/user_supabase_test.go` (fake repo + keySvc thoả interface — mirror fakes có sẵn trong package test nếu có; nếu chưa, định nghĩa fake tối thiểu):
```go
package service_test // external pkg — fake must implement full UserRepository

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	. "github.com/ennam/ennam-kg/internal/service"
)

func TestLoginWithSupabase_NewUserGetsViewer(t *testing.T) {
	repo := newFakeUserRepo()       // fake thoả UserRepository
	keys := newFakeKeySvc()         // fake thoả UserAPIKeyService, CreateKey trả PlaintextKey="k1"
	svc := NewUserService(repo, keys, nil)

	resp, err := svc.LoginWithSupabase(context.Background(),
		"sub-1", "new@exnodes.vn", map[string]bool{})
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if resp.User.Role != models.UserRoleViewer {
		t.Errorf("want viewer, got %s", resp.User.Role)
	}
	if resp.User.Status != models.UserStatusActive {
		t.Errorf("want active, got %s", resp.User.Status)
	}
	if resp.User.PasswordHash != nil {
		t.Error("supabase user must have nil password_hash")
	}
	if resp.APIKey == "" {
		t.Error("expected minted api key")
	}
}

func TestLoginWithSupabase_AllowlistGetsAdmin(t *testing.T) {
	svc := NewUserService(newFakeUserRepo(), newFakeKeySvc(), nil)
	resp, err := svc.LoginWithSupabase(context.Background(),
		"sub-2", "admin@ennam.vn", map[string]bool{"admin@ennam.vn": true})
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if resp.User.Role != models.UserRoleAdmin {
		t.Errorf("want admin, got %s", resp.User.Role)
	}
}

func TestLoginWithSupabase_ExistingUserNoDuplicate(t *testing.T) {
	repo := newFakeUserRepo()
	svc := NewUserService(repo, newFakeKeySvc(), nil)
	_, _ = svc.LoginWithSupabase(context.Background(), "sub-3", "x@exnodes.vn", map[string]bool{})
	_, err := svc.LoginWithSupabase(context.Background(), "sub-3", "x@exnodes.vn", map[string]bool{})
	if err != nil {
		t.Fatalf("second login err: %v", err)
	}
	if repo.countBySupabase("sub-3") != 1 {
		t.Errorf("expected 1 user for sub-3, got %d", repo.countBySupabase("sub-3"))
	}
}

func TestLoginWithSupabase_DisabledRejected(t *testing.T) {
	repo := newFakeUserRepo()
	repo.seedDisabled("sub-4", "dis@exnodes.vn")
	svc := NewUserService(repo, newFakeKeySvc(), nil)
	if _, err := svc.LoginWithSupabase(context.Background(), "sub-4", "dis@exnodes.vn", map[string]bool{}); err == nil {
		t.Error("expected error for disabled user")
	}
}
```
> Đọc test file service hiện có để tái dùng fake `UserRepository`/`UserAPIKeyService` nếu đã tồn tại; chỉ thêm `GetBySupabaseID/CreateSupabaseUser/SetSupabaseID` + helper `countBySupabase/seedDisabled` vào fake.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ennam.kg.go && go test ./internal/service/ -run TestLoginWithSupabase -v
```
Expected: FAIL (method undefined).

- [ ] **Step 3: Write minimal implementation**

Thêm vào `internal/service/user.go`:
```go
// LoginWithSupabase resolves a Supabase identity to a DAAB user (JIT-provision on
// first login, role viewer unless email is in adminEmails), then mints a web-session
// API key exactly like Login. Supabase users have no DAAB password.
func (s *UserService) LoginWithSupabase(ctx context.Context, sub, email string, adminEmails map[string]bool) (*LoginResponse, error) {
	user, err := s.repo.GetBySupabaseID(ctx, sub)
	if err != nil {
		return nil, fmt.Errorf("supabase login: %w", err)
	}

	if user == nil {
		// Link if a legacy user already owns this email; else create fresh.
		if existing, _ := s.repo.GetByEmail(ctx, email); existing != nil {
			user, err = s.repo.SetSupabaseID(ctx, existing.ID, sub)
			if err != nil {
				return nil, fmt.Errorf("supabase login: link: %w", err)
			}
		} else {
			role := models.UserRoleViewer
			if adminEmails[strings.ToLower(email)] {
				role = models.UserRoleAdmin
			}
			user, err = s.repo.CreateSupabaseUser(ctx, &models.User{
				Username:       email,
				Email:          &email,
				DisplayName:    email,
				Role:           role,
				Status:         models.UserStatusActive,
				SupabaseUserID: &sub,
			})
			if err != nil {
				return nil, fmt.Errorf("supabase login: create: %w", err)
			}
		}
	}

	if user.Status == models.UserStatusDisabled {
		return nil, fmt.Errorf("account disabled")
	}

	// Mint session key — same pattern as Login (revoke old web-session key first).
	if user.APIKeyID != nil {
		if oldKey, getErr := s.keySvc.GetKey(ctx, *user.APIKeyID); getErr == nil && oldKey != nil && strings.HasPrefix(oldKey.Label, "web-session-") {
			_, _ = s.keySvc.RevokeKey(ctx, RevokeKeyRequest{ID: *user.APIKeyID})
		}
	}
	keyResp, err := s.keySvc.CreateKey(ctx, CreateKeyRequest{
		DeveloperName: user.Username,
		Label:         fmt.Sprintf("web-session-%s", user.Username),
		Role:          user.Role.ToAPIKeyRole(),
		ProjectIDs:    []string{},
		Internal:      true,
	})
	if err != nil {
		return nil, fmt.Errorf("supabase login: create session api key: %w", err)
	}
	if err := s.repo.UpdateAPIKeyID(ctx, user.ID, &keyResp.Key.ID); err != nil {
		s.logger.Warn("failed to update api_key_id after supabase login", "user_id", user.ID, "error", err)
	}
	_ = s.repo.UpdateLoginSuccess(ctx, user.ID)
	user.APIKeyID = &keyResp.Key.ID

	s.logger.Info("user logged in via supabase", "user_id", user.ID, "email", email)
	return &LoginResponse{User: user, APIKey: keyResp.PlaintextKey}, nil
}
```
> Nếu `UserRepository` chưa có `GetByEmail`, thêm signature + impl store (`SELECT userColumns FROM users WHERE email=$1`, trả `(nil,nil)` nếu ErrNoRows) — hoặc bỏ nhánh link nếu OQ-3 chốt "không link". Mặc định plan: có `GetByEmail` để link (OQ-3 = link).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ennam.kg.go && go test ./internal/service/ -run TestLoginWithSupabase -race -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/service/user.go internal/service/user_supabase_test.go internal/store/user.go
git -C ennam.kg.go commit -m "feat(auth): UserService.LoginWithSupabase (JIT viewer + allowlist admin)"
```

---

## Task 4: Handler `/api/v1/auth/supabase` + middleware exempt + wiring

**Files:**
- Modify: `internal/handler/auth.go` (deps + struct + route + handler), `internal/middleware/auth.go` (`isExemptPath` :292), `cmd/kg-server/main.go` (:713 area)
- Test: `internal/handler/auth_test.go` (or new `auth_supabase_test.go`), `internal/middleware/auth_test.go` (`TestIsExemptPath` :465)

**Interfaces:**
- Consumes: `supabaseauth.Verifier.Verify` (Task 2), `UserService.LoginWithSupabase` (Task 3).
- Produces: `POST /api/v1/auth/supabase` accepting `{"access_token": "..."}` → `loginResponse` JSON.

- [ ] **Step 1: Extend AuthHandler deps + route**

`internal/handler/auth.go` — thêm field + constructor param + interface verifier (để test inject fake):
```go
// SupabaseVerifier verifies a Supabase access token and returns identity claims.
type SupabaseVerifier interface {
	Verify(ctx context.Context, raw string) (*supabaseauth.Claims, error)
}

type AuthHandler struct {
	userService *service.UserService
	verifier    SupabaseVerifier // nil ⇒ supabase login disabled (503)
	adminEmails map[string]bool
	logger      *slog.Logger
}
```
Cập nhật `NewAuthHandler(userService, verifier, adminEmails, logger)` gán các field (verifier có thể nil). Thêm import `supabaseauth`.
Thêm route trong `RegisterRoutes`:
```go
	mux.HandleFunc("POST /api/v1/auth/supabase", h.SupabaseLogin)
```
Thêm struct request:
```go
type supabaseLoginRequest struct {
	AccessToken string `json:"access_token"`
}
```

- [ ] **Step 2: Write the failing test**

`internal/handler/auth_supabase_test.go`:
> **Verified:** handler tests = `package handler` (set field unexported OK). ⚠️ `SupabaseLogin` gọi `h.logger.InfoContext` ở nhánh verify-fail → **literal `&AuthHandler{}` phải set `logger: slog.Default()`** nếu không **panic nil logger**. Set logger cho mọi literal.
```go
package handler

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/supabaseauth"
)

type fakeVerifier struct {
	claims *supabaseauth.Claims
	err    error
}

func (f fakeVerifier) Verify(_ context.Context, _ string) (*supabaseauth.Claims, error) {
	return f.claims, f.err
}

func TestSupabaseLogin_DisabledWhenNoVerifier(t *testing.T) {
	h := &AuthHandler{logger: slog.Default()} // verifier nil
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/supabase",
		strings.NewReader(`{"access_token":"x"}`))
	h.SupabaseLogin(rr, req)
	if rr.Code != http.StatusServiceUnavailable {
		t.Errorf("want 503, got %d", rr.Code)
	}
}

func TestSupabaseLogin_InvalidToken401(t *testing.T) {
	h := &AuthHandler{verifier: fakeVerifier{err: context.DeadlineExceeded}, logger: slog.Default()}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/supabase",
		strings.NewReader(`{"access_token":"bad"}`))
	h.SupabaseLogin(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Errorf("want 401, got %d", rr.Code)
	}
}

func TestSupabaseLogin_MissingToken400(t *testing.T) {
	h := &AuthHandler{verifier: fakeVerifier{}, logger: slog.Default()}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/supabase",
		strings.NewReader(`{}`))
	h.SupabaseLogin(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Errorf("want 400, got %d", rr.Code)
	}
}
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd ennam.kg.go && go test ./internal/handler/ -run TestSupabaseLogin -v
```
Expected: FAIL (SupabaseLogin undefined).

- [ ] **Step 4: Write the handler**

Thêm vào `internal/handler/auth.go`:
```go
// SupabaseLogin handles POST /api/v1/auth/supabase (PUBLIC).
// Verifies a Supabase access token, JIT-provisions the user, returns an internal API key.
func (h *AuthHandler) SupabaseLogin(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	if h.verifier == nil {
		errorResponse(w, http.StatusServiceUnavailable, "supabase login is not enabled")
		return
	}

	var req supabaseLoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}
	if req.AccessToken == "" {
		errorResponse(w, http.StatusBadRequest, "access_token is required")
		return
	}

	claims, err := h.verifier.Verify(ctx, req.AccessToken)
	if err != nil {
		h.logger.InfoContext(ctx, "supabase token rejected", "error", err)
		errorResponse(w, http.StatusUnauthorized, "invalid or expired token")
		return
	}

	resp, err := h.userService.LoginWithSupabase(ctx, claims.Sub, claims.Email, h.adminEmails)
	if err != nil {
		if strings.Contains(err.Error(), "disabled") {
			errorResponse(w, http.StatusForbidden, "account disabled")
			return
		}
		h.logger.Error("supabase login failed", "email", claims.Email, "error", err)
		errorResponse(w, http.StatusInternalServerError, "login failed")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(loginResponse{
		User:                   resp.User,
		APIKey:                 resp.APIKey,
		RequiresPasswordChange: false,
	})
}
```

- [ ] **Step 5: Add middleware exempt + test**

`internal/middleware/auth.go` `isExemptPath` (:292), thêm case cạnh `/api/v1/auth/login`:
```go
	case "/api/v1/auth/supabase":
		return true
```
`internal/middleware/auth_test.go` `TestIsExemptPath` (:472 table), thêm dòng:
```go
		{"/api/v1/auth/supabase", true},
```

- [ ] **Step 6: Wire in main.go**

`cmd/kg-server/main.go` quanh dòng 713 (`authHandler := handler.NewAuthHandler(userService, logger)`), thay bằng:
```go
	var supaVerifier handler.SupabaseVerifier
	adminEmails := map[string]bool{}
	if supaURL := strings.TrimSpace(os.Getenv("KG_SUPABASE_URL")); supaURL != "" {
		jwksURL := supaURL + "/auth/v1/.well-known/jwks.json"
		ks, err := supabaseauth.NewCachedKeySource(ctx, jwksURL)
		if err != nil {
			logger.Error("supabase jwks unavailable — supabase login disabled", "error", err)
		} else {
			supaVerifier = supabaseauth.NewVerifier(ks, supaURL+"/auth/v1", "authenticated")
			for _, e := range strings.Split(os.Getenv("KG_SUPABASE_ADMIN_EMAILS"), ",") {
				if e = strings.ToLower(strings.TrimSpace(e)); e != "" {
					adminEmails[e] = true
				}
			}
			logger.Info("supabase login enabled", "issuer", supaURL+"/auth/v1", "admin_emails", len(adminEmails))
		}
	}
	authHandler := handler.NewAuthHandler(userService, supaVerifier, adminEmails, logger)
	authHandler.RegisterRoutes(apiMux)
```
> **Verified:** `ctx` tồn tại ở `run()` (main.go:68 `ctx, stop := signal.NotifyContext(...)`) — dùng trực tiếp. Đảm bảo import `os`, `strings`, `supabaseauth` (thêm nếu thiếu). Khi `ctx` huỷ (shutdown) cache JWKS ngừng refresh — đúng ý.

- [ ] **Step 7: Run all affected tests + build**

```bash
cd ennam.kg.go && go test ./internal/handler/ ./internal/middleware/ -race -run "TestSupabaseLogin|TestIsExemptPath" -v && go build ./...
```
Expected: PASS + build OK.

- [ ] **Step 8: Commit**

```bash
git -C ennam.kg.go add internal/handler/auth.go internal/handler/auth_supabase_test.go internal/middleware/auth.go internal/middleware/auth_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(auth): POST /api/v1/auth/supabase endpoint + wiring + exempt path"
```

---

## Task 5: Integration check với token Supabase thật (gated)

**Files:**
- Test: `internal/supabaseauth/verifier_integration_test.go` (create, build tag `//go:build integration`)

**Interfaces:** Consumes `NewCachedKeySource` + `Verifier` (Task 2).

- [ ] **Step 1: Write integration test (live JWKS)**

```go
//go:build integration

package supabaseauth

import (
	"context"
	"os"
	"testing"
)

// Run: SUPABASE_TEST_TOKEN=<fresh access_token> go test -tags integration ./internal/supabaseauth/ -run TestVerify_RealToken -v
func TestVerify_RealToken(t *testing.T) {
	raw := os.Getenv("SUPABASE_TEST_TOKEN")
	if raw == "" {
		t.Skip("set SUPABASE_TEST_TOKEN (fresh, unexpired) to run")
	}
	const url = "https://nicrcubktflnwdkhotut.supabase.co"
	ks, err := NewCachedKeySource(context.Background(), url+"/auth/v1/.well-known/jwks.json")
	if err != nil {
		t.Fatalf("jwks: %v", err)
	}
	v := NewVerifier(ks, url+"/auth/v1", "authenticated")
	c, err := v.Verify(context.Background(), raw)
	if err != nil {
		t.Fatalf("verify real token: %v", err)
	}
	t.Logf("verified sub=%s email=%s", c.Sub, c.Email)
}
```

- [ ] **Step 2: Run with a fresh token**

Lấy token mới (token cũ hết hạn ~1h):
```bash
curl -s -X POST "https://nicrcubktflnwdkhotut.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: sb_publishable_TT5H3qIx5dC8UPBTsbvn-A_JCs5zucU" \
  -H "Content-Type: application/json" \
  -d '{"email":"dragoon@exnodes.vn","password":"Dev123!@#"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"
```
```bash
cd ennam.kg.go && SUPABASE_TEST_TOKEN="<token>" go test -tags integration ./internal/supabaseauth/ -run TestVerify_RealToken -v
```
Expected: PASS, log sub=`e7028d06-…` email=`dragoon@exnodes.vn`.

- [ ] **Step 3: Commit**

```bash
git -C ennam.kg.go add internal/supabaseauth/verifier_integration_test.go
git -C ennam.kg.go commit -m "test(auth): integration verify of real supabase token (gated)"
```

---

## Task 6: Frontend — Supabase client + login action + 2-tab UI

**Files:**
- Create: `src/lib/supabase/client.ts`
- Modify: `src/app/(auth)/login/actions.ts`, `src/app/(auth)/login/page.tsx`, `.env.local.example`, `package.json`
- Test: E2E thủ công (mục Success criteria) — không thêm unit test FE trong slice này (component nặng UI, theo testing rule ưu tiên E2E).

**Interfaces:**
- Consumes: `POST /api/v1/auth/supabase` (Task 4) qua GO_API_URL.
- Produces: `supabaseLoginAction(prevState, formData)` server action; `getSupabaseBrowserClient()`.

- [ ] **Step 1: Add dependency + env example**

```bash
cd ennam.kg.next && npm install @supabase/supabase-js
```
`.env.local.example` thêm:
```
NEXT_PUBLIC_SUPABASE_URL=https://nicrcubktflnwdkhotut.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_TT5H3qIx5dC8UPBTsbvn-A_JCs5zucU
```

- [ ] **Step 2: Browser client**

`src/lib/supabase/client.ts`:
```ts
'use client';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';

let client: SupabaseClient | null = null;

export function getSupabaseBrowserClient(): SupabaseClient {
  if (client) return client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anon) throw new Error('Supabase env not configured');
  client = createClient(url, anon, { auth: { persistSession: false } });
  return client;
}
```

- [ ] **Step 3: Server action**

Thêm vào `src/app/(auth)/login/actions.ts`:
```ts
export async function supabaseLoginAction(
  _prevState: LoginState,
  formData: FormData,
): Promise<LoginState> {
  const accessToken = formData.get('access_token') as string;
  if (!accessToken) return { error: 'Missing Supabase token' };

  const goApiUrl = process.env.GO_API_URL || 'http://localhost:8080';
  try {
    const res = await fetch(`${goApiUrl}/api/v1/auth/supabase`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: accessToken }),
    });
    if (res.status === 401) return { error: 'Supabase token invalid or expired' };
    if (res.status === 403) return { error: 'Account disabled. Contact admin.' };
    if (res.status === 503) return { error: 'Supabase login not enabled on server' };
    if (!res.ok) return { error: 'Login failed. Please try again.' };

    const data = await res.json();
    const session = await getSession();
    session.apiKey = data.api_key;
    session.userId = data.user.id;
    session.username = data.user.username;
    session.displayName = data.user.display_name;
    session.role = data.user.role;
    session.isLoggedIn = true;
    session.requiresPasswordChange = false;
    await session.save();
  } catch (err) {
    if (err instanceof Error && err.message === 'NEXT_REDIRECT') throw err;
    return { error: 'Cannot reach API server' };
  }
  redirect('/');
}
```

- [ ] **Step 4: Login page — 2 tab**

Sửa `src/app/(auth)/login/page.tsx`: thêm state tab (`'supabase' | 'admin'`, mặc định `supabase`). Tab **Supabase** = form email+password gọi (client) `getSupabaseBrowserClient().auth.signInWithPassword(...)` → lấy `data.session.access_token` → set vào hidden input của form `action={supabaseFormAction}` (dùng `useActionState(supabaseLoginAction, initialState)`), submit. Tab **Admin** = giữ NGUYÊN form username/password hiện tại (`loginAction`). Mẫu phần Supabase tab:
```tsx
'use client';
// ...imports: useState, getSupabaseBrowserClient, supabaseLoginAction
const [tab, setTab] = useState<'supabase' | 'admin'>('supabase');
const [sbState, sbAction, sbPending] = useActionState(supabaseLoginAction, initialState);
const [sbError, setSbError] = useState<string | null>(null);

async function handleSupabaseSubmit(e: React.FormEvent<HTMLFormElement>) {
  e.preventDefault();
  setSbError(null);
  const fd = new FormData(e.currentTarget);
  const email = String(fd.get('email'));
  const password = String(fd.get('password'));
  const { data, error } = await getSupabaseBrowserClient().auth.signInWithPassword({ email, password });
  if (error || !data.session) { setSbError(error?.message ?? 'Login failed'); return; }
  const tokenForm = new FormData();
  tokenForm.set('access_token', data.session.access_token);
  sbAction(tokenForm);
}
```
Render: 2 nút chuyển tab; tab supabase dùng `<form onSubmit={handleSupabaseSubmit}>` với input `email`+`password`; hiển thị `sbError || sbState.error`. Tab admin render form hiện tại (không đổi). Giữ nguyên layout/Style hiện có (FallingPattern, card…).

- [ ] **Step 5: Build**

```bash
cd ennam.kg.next && npm run build
```
Expected: build standalone OK (no type errors).

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.next add src/lib/supabase/client.ts "src/app/(auth)/login/actions.ts" "src/app/(auth)/login/page.tsx" .env.local.example package.json package-lock.json
git -C ennam.kg.next commit -m "feat(auth): supabase login tab (coexist with legacy username/password)"
```

---

## Task 7: End-to-end verify + enable locally + security review

**Files:** Modify `docker-compose.yml` (env), then run stack.

- [ ] **Step 1: Enable supabase login for kg-server + dashboard**

`docker-compose.yml` — service `kg-server` env thêm:
```yaml
      KG_SUPABASE_URL: ${KG_SUPABASE_URL:-https://nicrcubktflnwdkhotut.supabase.co}
      KG_SUPABASE_ADMIN_EMAILS: ${KG_SUPABASE_ADMIN_EMAILS:-admin@ennam.vn}
```
`dashboard` env thêm:
```yaml
      NEXT_PUBLIC_SUPABASE_URL: ${NEXT_PUBLIC_SUPABASE_URL:-https://nicrcubktflnwdkhotut.supabase.co}
      NEXT_PUBLIC_SUPABASE_ANON_KEY: ${NEXT_PUBLIC_SUPABASE_ANON_KEY:-sb_publishable_TT5H3qIx5dC8UPBTsbvn-A_JCs5zucU}
```

- [ ] **Step 2: Rebuild + run**

```bash
docker compose up -d --build kg-server dashboard
docker compose logs kg-server | grep -i "supabase login enabled"
```
Expected: log "supabase login enabled".

- [ ] **Step 3: E2E — Supabase login via API**

```bash
TOKEN=$(curl -s -X POST "https://nicrcubktflnwdkhotut.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: sb_publishable_TT5H3qIx5dC8UPBTsbvn-A_JCs5zucU" -H "Content-Type: application/json" \
  -d '{"email":"dragoon@exnodes.vn","password":"Dev123!@#"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST http://localhost:8080/api/v1/auth/supabase -H "Content-Type: application/json" \
  -d "{\"access_token\":\"$TOKEN\"}" | python3 -m json.tool
```
Expected: JSON có `api_key`, `user.role == "viewer"`, `user.username == "dragoon@exnodes.vn"`. Verify DB: user mới với `supabase_user_id=e7028d06-…`, `password_hash` NULL, `status=active`.

- [ ] **Step 4: E2E — legacy admin không regression**

```bash
curl -s -X POST http://localhost:8080/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin123"}' | python3 -c "import sys,json;print('ok' if json.load(sys.stdin).get('api_key') else 'FAIL')"
```
Expected: `ok`.

- [ ] **Step 5: Browser E2E**

Mở `http://localhost:3500/login` → tab "Email (Supabase)" login `dragoon@exnodes.vn`/`Dev123!@#` → vào dashboard (role viewer, 0 project → trống là đúng). Tab "Admin" login `admin`/`Admin123` → vào dashboard. (Optional: Playwright e2e-runner.)

- [ ] **Step 6: Security review**

Dispatch `security-reviewer` agent trên: `internal/supabaseauth/`, `internal/handler/auth.go` (SupabaseLogin), `cmd/kg-server/main.go` (wiring), `src/app/(auth)/login/actions.ts`. Address CRITICAL/HIGH.

- [ ] **Step 7: Commit**

```bash
git -C . add docker-compose.yml
git commit -m "chore(auth): enable supabase login in docker-compose (kg-server + dashboard)"
```

---

## Self-Review (đã chạy)

- **Spec coverage:** §4 luồng → Task 4/6; §5 migration → Task 1; §6.2 verifier → Task 2; §6.3 handler → Task 4; §6.4 service → Task 3; §6.5 middleware → Task 4; §7 FE → Task 6; §8 bootstrap allowlist → Task 3 (admin role) + Task 7 (env); §12 test plan → Task 5/7. ✅
- **Placeholder scan:** mọi step code có nội dung thật; 3 chỗ ghi rõ "đọc file trước khi sửa" (interface UserRepository, fakes test, scan helpers) — không phải placeholder mà là hướng dẫn áp dụng vào code có sẵn.
- **Type consistency:** `Claims{Sub,Email}`, `KeySource.KeySet`, `Verifier.Verify`, `LoginWithSupabase(ctx,sub,email,adminEmails)`, `SupabaseVerifier` interface — nhất quán giữa Task 2/3/4. `loginResponse` tái dùng (User/APIKey/RequiresPasswordChange) khớp auth.go hiện tại. ✅
- **Outstanding decisions (từ spec OQ, không chặn):** OQ-2 (bật local) = plan Task 7 BẬT mặc định trong compose; OQ-3 (email trùng) = plan chọn **link** (`GetByEmail`); OQ-4/5 (expiry/logout) = ngoài scope slice.

## Open dependencies cần xác nhận khi execute (đã verify phần lớn)
- ✅ `UserRepository` đã có `UpdateLoginSuccess`/`UpdateAPIKeyID`; `UserAPIKeyService` đã có `GetKey/RevokeKey/CreateKey`. Chỉ cần **thêm 4 method** (`GetBySupabaseID/GetByEmail/CreateSupabaseUser/SetSupabaseID`) vào interface + impl `*store.UserStore` (Task 1).
- ✅ `NewUserService` default nil logger an toàn (test truyền nil OK). `LoginResponse.User` = `*models.User` (`resp.User.Role` chạy).
- ✅ Store DB test = `package store_test` + `setupTestDB` (skip nếu thiếu `KG_TEST_DATABASE_URL`); service test = `package service_test` (fake implement full interface).
- ⚠️ jwx: pin `v2.1.3`, `go get` cần network (chạy ở env có mạng nếu sandbox chặn).
- ⚠️ Tên biến `ctx` lifecycle ở `main.go` (Task 4 Step 6) — dùng đúng biến context server đang có (đọc quanh dòng 700-715 trước khi sửa).
- ⚠️ Task 3 test: nếu `package service_test` đã có fake `UserRepository` dùng chung, tái dùng + chỉ thêm 4 method; tránh khai trùng `strptr`/fake.
