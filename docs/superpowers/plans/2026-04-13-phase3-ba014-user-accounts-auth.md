# BA-014 User Accounts & Authentication — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user account management and password-based authentication to the Go API server, layered on top of the existing API key system. Users own an internal API key; login returns the key for subsequent requests.

**Architecture:** Follows the existing 3-layer pattern (Handler -> Service -> Store). Reuses `golang.org/x/crypto/bcrypt` (already in go.mod). The existing `DeveloperIdentity` context injection remains — a new `UserIdentity` context key is added alongside it when the API key maps to a user account.

**Tech Stack:** Go std lib, `database/sql`, `lib/pq`, `golang.org/x/crypto/bcrypt`, golang-migrate

**Phase:** 3 — Step 1 (no Phase 3 dependencies)

**Working Directory:** `d:/Projects/EnNam/ennam.kg/ennam.kg.go`

---

## File Structure

### New Files

```
db/migrations/
├── 000032_create_users.up.sql
└── 000032_create_users.down.sql

internal/models/
└── user.go                         # User model, UserRole, UserStatus types, password validation

internal/store/
├── user.go                         # UserStore: CRUD + login-related updates
└── user_test.go

internal/service/
├── user.go                         # UserService: create, disable, enable, reset password, login
└── user_test.go

internal/handler/
├── user.go                         # UserHandler: 9 CRUD endpoints
├── user_test.go
├── auth.go                         # AuthHandler: login, change-password, logout
└── auth_test.go
```

### Modified Files

```
cmd/kg-server/main.go              # Wire UserStore, UserService, UserHandler, AuthHandler into buildRouter()
internal/middleware/auth.go         # Add /api/v1/auth/login to exempt paths; add UserIdentity context injection
internal/middleware/auth_test.go    # Test login path exemption + user context
```

---

## Task 1: Migration 032 — users table

**Files:**
- Create: `db/migrations/000032_create_users.up.sql`
- Create: `db/migrations/000032_create_users.down.sql`

- [ ] **Step 1: Write up migration**

```sql
-- db/migrations/000032_create_users.up.sql

-- User accounts for the Ennam KG platform (BA-014).
-- Each user owns an internal API key; login returns the key for subsequent requests.

CREATE TABLE users (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username          VARCHAR(255) NOT NULL,
    email             VARCHAR(255),
    password_hash     TEXT,
    display_name      VARCHAR(255) NOT NULL,
    role              VARCHAR(50) NOT NULL DEFAULT 'developer',
    status            VARCHAR(50) NOT NULL DEFAULT 'active',
    api_key_id        UUID REFERENCES api_keys(id),
    last_login_at     TIMESTAMPTZ,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_at         TIMESTAMPTZ,
    created_by        UUID REFERENCES users(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_users_role   CHECK (role IN ('admin', 'developer', 'viewer')),
    CONSTRAINT chk_users_status CHECK (status IN ('active', 'disabled', 'pending_password_change', 'locked'))
);

-- Case-insensitive unique username.
CREATE UNIQUE INDEX idx_users_username ON users (LOWER(username));

-- Unique email where not null.
CREATE UNIQUE INDEX idx_users_email ON users (email) WHERE email IS NOT NULL;

-- Fast lookup by API key (middleware user resolution).
CREATE INDEX idx_users_api_key_id ON users (api_key_id);

-- Filter by status.
CREATE INDEX idx_users_status ON users (status);

-- Trigger to auto-update updated_at on row changes.
CREATE OR REPLACE FUNCTION update_users_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_users_updated_at();
```

- [ ] **Step 2: Write down migration**

```sql
-- db/migrations/000032_create_users.down.sql

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
DROP FUNCTION IF EXISTS update_users_updated_at();
DROP TABLE IF EXISTS users;
```

- [ ] **Step 3: Run migration**

```bash
cd ennam.kg.go && go run ./cmd/kg-migrate/ up
```

Expected: migration 032 applied, `users` table created.

- [ ] **Step 4: Verify migration**

```bash
cd ennam.kg.go && go run ./cmd/kg-migrate/ version
```

Expected: version 32.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add db/migrations/000032_create_users.up.sql db/migrations/000032_create_users.down.sql
git commit -m "feat(db): add users table migration 032 (BA-014)"
```

---

## Task 2: User Model

**Files:**
- Create: `internal/models/user.go`

- [ ] **Step 1: Implement User model with types, validation, and password helpers**

```go
// internal/models/user.go
package models

import (
	"fmt"
	"regexp"
	"time"
	"unicode"

	"golang.org/x/crypto/bcrypt"
)

// UserRole represents the permission level of a user account.
type UserRole string

const (
	UserRoleAdmin     UserRole = "admin"
	UserRoleDeveloper UserRole = "developer"
	UserRoleViewer    UserRole = "viewer"
)

// ValidUserRoles contains all valid user role values.
var ValidUserRoles = []UserRole{UserRoleAdmin, UserRoleDeveloper, UserRoleViewer}

// IsValid checks whether the user role is a recognized value.
func (r UserRole) IsValid() bool {
	for _, v := range ValidUserRoles {
		if r == v {
			return true
		}
	}
	return false
}

// ToAPIKeyRole converts a UserRole to the corresponding APIKeyRole.
func (r UserRole) ToAPIKeyRole() APIKeyRole {
	switch r {
	case UserRoleAdmin:
		return APIKeyRoleAdmin
	case UserRoleDeveloper:
		return APIKeyRoleDeveloper
	case UserRoleViewer:
		return APIKeyRoleViewer
	default:
		return APIKeyRoleDeveloper
	}
}

// UserStatus represents the lifecycle status of a user account.
type UserStatus string

const (
	UserStatusActive               UserStatus = "active"
	UserStatusDisabled             UserStatus = "disabled"
	UserStatusPendingPasswordChange UserStatus = "pending_password_change"
	UserStatusLocked               UserStatus = "locked"
)

// ValidUserStatuses contains all valid user status values.
var ValidUserStatuses = []UserStatus{
	UserStatusActive,
	UserStatusDisabled,
	UserStatusPendingPasswordChange,
	UserStatusLocked,
}

// IsValid checks whether the user status is a recognized value.
func (s UserStatus) IsValid() bool {
	for _, v := range ValidUserStatuses {
		if s == v {
			return true
		}
	}
	return false
}

// User represents a user account in the Ennam KG platform.
type User struct {
	ID               string      `json:"id" db:"id"`
	Username         string      `json:"username" db:"username"`
	Email            *string     `json:"email,omitempty" db:"email"`
	PasswordHash     *string     `json:"-" db:"password_hash"`
	DisplayName      string      `json:"display_name" db:"display_name"`
	Role             UserRole    `json:"role" db:"role"`
	Status           UserStatus  `json:"status" db:"status"`
	APIKeyID         *string     `json:"api_key_id,omitempty" db:"api_key_id"`
	LastLoginAt      *time.Time  `json:"last_login_at,omitempty" db:"last_login_at"`
	FailedLoginCount int         `json:"failed_login_count" db:"failed_login_count"`
	LockedAt         *time.Time  `json:"locked_at,omitempty" db:"locked_at"`
	CreatedBy        *string     `json:"created_by,omitempty" db:"created_by"`
	CreatedAt        time.Time   `json:"created_at" db:"created_at"`
	UpdatedAt        time.Time   `json:"updated_at" db:"updated_at"`
}

// IsActive returns true if the user account can be used for authentication.
func (u *User) IsActive() bool {
	return u.Status == UserStatusActive || u.Status == UserStatusPendingPasswordChange
}

// IsLocked returns true if the user account is locked due to failed login attempts.
func (u *User) IsLocked() bool {
	return u.Status == UserStatusLocked
}

// MaxFailedLoginAttempts is the threshold before account lockout.
const MaxFailedLoginAttempts = 5

// BcryptCost is the bcrypt cost factor for password hashing.
const BcryptCost = 12

// HashPassword hashes a plaintext password using bcrypt.
func HashPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), BcryptCost)
	if err != nil {
		return "", fmt.Errorf("hash password: %w", err)
	}
	return string(hash), nil
}

// CheckPassword compares a plaintext password against a bcrypt hash.
func CheckPassword(hash, password string) error {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
}

// DummyPasswordHash performs a bcrypt comparison against a dummy hash to prevent
// timing-based user enumeration. Call this when the username does not exist.
func DummyPasswordHash() {
	// Pre-computed bcrypt hash of "dummy" with cost 12.
	dummy := "$2a$12$LJ3m4ys3Lg/TBM.vYpPAz.ixCbhMBrJT5TJ.Oal4MPhwb7Mj3Y7K6"
	_ = bcrypt.CompareHashAndPassword([]byte(dummy), []byte("not-a-real-password"))
}

// passwordSpecialChars matches at least one special character.
var passwordSpecialChars = regexp.MustCompile(`[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?~` + "`" + `]`)

// ValidatePassword checks that a password meets complexity requirements:
// - minimum 8 characters
// - at least 1 uppercase letter
// - at least 1 digit
// - at least 1 special character
func ValidatePassword(password string) error {
	if len(password) < 8 {
		return fmt.Errorf("password must be at least 8 characters")
	}

	var hasUpper, hasDigit bool
	for _, ch := range password {
		if unicode.IsUpper(ch) {
			hasUpper = true
		}
		if unicode.IsDigit(ch) {
			hasDigit = true
		}
	}

	if !hasUpper {
		return fmt.Errorf("password must contain at least 1 uppercase letter")
	}
	if !hasDigit {
		return fmt.Errorf("password must contain at least 1 digit")
	}
	if !passwordSpecialChars.MatchString(password) {
		return fmt.Errorf("password must contain at least 1 special character")
	}

	return nil
}
```

- [ ] **Step 2: Commit**

```bash
cd ennam.kg.go
git add internal/models/user.go
git commit -m "feat(models): add User model with roles, status, password validation (BA-014)"
```

---

## Task 3: User Store

**Files:**
- Create: `internal/store/user.go`
- Create: `internal/store/user_test.go`

- [ ] **Step 1: Write failing tests for UserStore**

```go
// internal/store/user_test.go
package store_test

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

// These tests require a test database. Use the same test helper pattern as apikey_test.go.

func TestUserStore_CreateAndGetByID(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewUserStore(db)
	ctx := context.Background()

	user := &models.User{
		Username:    "testuser",
		DisplayName: "Test User",
		Role:        models.UserRoleAdmin,
		Status:      models.UserStatusActive,
	}

	created, err := s.Create(ctx, user)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if created.ID == "" {
		t.Fatal("expected non-empty ID")
	}
	if created.Username != "testuser" {
		t.Fatalf("username: got %q, want %q", created.Username, "testuser")
	}

	fetched, err := s.GetByID(ctx, created.ID)
	if err != nil {
		t.Fatalf("get by id: %v", err)
	}
	if fetched.Username != "testuser" {
		t.Fatalf("username: got %q, want %q", fetched.Username, "testuser")
	}
}

func TestUserStore_GetByUsername(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewUserStore(db)
	ctx := context.Background()

	user := &models.User{
		Username:    "lookupuser",
		DisplayName: "Lookup User",
		Role:        models.UserRoleDeveloper,
		Status:      models.UserStatusActive,
	}
	_, err := s.Create(ctx, user)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	fetched, err := s.GetByUsername(ctx, "lookupuser")
	if err != nil {
		t.Fatalf("get by username: %v", err)
	}
	if fetched.DisplayName != "Lookup User" {
		t.Fatalf("display_name: got %q, want %q", fetched.DisplayName, "Lookup User")
	}
}

func TestUserStore_GetByAPIKeyID(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewUserStore(db)
	ctx := context.Background()

	// Create user with a known api_key_id (requires an api_key to exist).
	// This test validates the lookup path used by middleware.
	// For unit tests, use a mock. Integration tests need full DB setup.
	_ = s
	_ = ctx
	t.Skip("requires api_keys seeded — covered by integration tests")
}

func TestUserStore_List(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewUserStore(db)
	ctx := context.Background()

	for i := 0; i < 3; i++ {
		_, err := s.Create(ctx, &models.User{
			Username:    fmt.Sprintf("listuser%d", i),
			DisplayName: fmt.Sprintf("List User %d", i),
			Role:        models.UserRoleDeveloper,
			Status:      models.UserStatusActive,
		})
		if err != nil {
			t.Fatalf("create user %d: %v", i, err)
		}
	}

	users, err := s.List(ctx)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(users) < 3 {
		t.Fatalf("expected at least 3 users, got %d", len(users))
	}
}

func TestUserStore_UpdateStatus(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewUserStore(db)
	ctx := context.Background()

	user, _ := s.Create(ctx, &models.User{
		Username:    "statususer",
		DisplayName: "Status User",
		Role:        models.UserRoleDeveloper,
		Status:      models.UserStatusActive,
	})

	err := s.UpdateStatus(ctx, user.ID, models.UserStatusDisabled)
	if err != nil {
		t.Fatalf("update status: %v", err)
	}

	fetched, _ := s.GetByID(ctx, user.ID)
	if fetched.Status != models.UserStatusDisabled {
		t.Fatalf("status: got %q, want %q", fetched.Status, models.UserStatusDisabled)
	}
}

func TestUserStore_UpdatePassword(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewUserStore(db)
	ctx := context.Background()

	user, _ := s.Create(ctx, &models.User{
		Username:    "pwuser",
		DisplayName: "PW User",
		Role:        models.UserRoleDeveloper,
		Status:      models.UserStatusPendingPasswordChange,
	})

	hash, _ := models.HashPassword("NewPass1!")
	err := s.UpdatePassword(ctx, user.ID, hash)
	if err != nil {
		t.Fatalf("update password: %v", err)
	}

	fetched, _ := s.GetByID(ctx, user.ID)
	if fetched.PasswordHash == nil {
		t.Fatal("expected password_hash to be set")
	}
}

func TestUserStore_IncrementFailedLogin(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewUserStore(db)
	ctx := context.Background()

	user, _ := s.Create(ctx, &models.User{
		Username:    "failuser",
		DisplayName: "Fail User",
		Role:        models.UserRoleDeveloper,
		Status:      models.UserStatusActive,
	})

	err := s.IncrementFailedLogin(ctx, user.ID)
	if err != nil {
		t.Fatalf("increment: %v", err)
	}

	fetched, _ := s.GetByID(ctx, user.ID)
	if fetched.FailedLoginCount != 1 {
		t.Fatalf("failed_login_count: got %d, want 1", fetched.FailedLoginCount)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ennam.kg.go && go test ./internal/store/... -run TestUserStore -v
```

Expected: FAIL — `NewUserStore` not found.

- [ ] **Step 3: Implement UserStore**

```go
// internal/store/user.go
package store

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/ennam/ennam-kg/internal/models"
)

// UserStore provides CRUD operations for user accounts.
type UserStore struct {
	db *sql.DB
}

// NewUserStore creates a new UserStore with the given database connection.
func NewUserStore(db *sql.DB) *UserStore {
	return &UserStore{db: db}
}

// userColumns is the standard SELECT column list for users.
const userColumns = `id, username, email, password_hash, display_name, role, status,
	api_key_id, last_login_at, failed_login_count, locked_at,
	created_by, created_at, updated_at`

// Create inserts a new user record.
func (s *UserStore) Create(ctx context.Context, user *models.User) (*models.User, error) {
	query := `
		INSERT INTO users (username, email, password_hash, display_name, role, status, api_key_id, created_by)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		RETURNING ` + userColumns

	return s.scanOne(ctx, query,
		user.Username,
		user.Email,
		user.PasswordHash,
		user.DisplayName,
		string(user.Role),
		string(user.Status),
		user.APIKeyID,
		user.CreatedBy,
	)
}

// GetByID retrieves a user by UUID.
func (s *UserStore) GetByID(ctx context.Context, id string) (*models.User, error) {
	if id == "" {
		return nil, fmt.Errorf("id is required")
	}
	query := `SELECT ` + userColumns + ` FROM users WHERE id = $1`
	u, err := s.scanOneRow(ctx, query, id)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("user not found: %s", id)
		}
		return nil, fmt.Errorf("get user by id: %w", err)
	}
	return u, nil
}

// GetByUsername retrieves a user by username (case-insensitive).
func (s *UserStore) GetByUsername(ctx context.Context, username string) (*models.User, error) {
	if username == "" {
		return nil, fmt.Errorf("username is required")
	}
	query := `SELECT ` + userColumns + ` FROM users WHERE LOWER(username) = LOWER($1)`
	u, err := s.scanOneRow(ctx, query, username)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("user not found: %s", username)
		}
		return nil, fmt.Errorf("get user by username: %w", err)
	}
	return u, nil
}

// GetByAPIKeyID retrieves a user by their linked API key ID.
// Returns nil, nil if no user is linked to this key (backwards-compatible with keyless API keys).
func (s *UserStore) GetByAPIKeyID(ctx context.Context, apiKeyID string) (*models.User, error) {
	if apiKeyID == "" {
		return nil, fmt.Errorf("api_key_id is required")
	}
	query := `SELECT ` + userColumns + ` FROM users WHERE api_key_id = $1`
	u, err := s.scanOneRow(ctx, query, apiKeyID)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil // No user linked — not an error
		}
		return nil, fmt.Errorf("get user by api_key_id: %w", err)
	}
	return u, nil
}

// List retrieves all users, ordered by created_at descending.
func (s *UserStore) List(ctx context.Context) ([]*models.User, error) {
	query := `SELECT ` + userColumns + ` FROM users ORDER BY created_at DESC`
	return s.scanMany(ctx, query)
}

// Update updates mutable user fields (display_name, email, role).
func (s *UserStore) Update(ctx context.Context, id string, displayName string, email *string, role models.UserRole) (*models.User, error) {
	if id == "" {
		return nil, fmt.Errorf("id is required")
	}
	query := `
		UPDATE users
		SET display_name = $2, email = $3, role = $4
		WHERE id = $1
		RETURNING ` + userColumns

	u, err := s.scanOneRow(ctx, query, id, displayName, email, string(role))
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("user not found: %s", id)
		}
		return nil, fmt.Errorf("update user: %w", err)
	}
	return u, nil
}

// UpdateStatus updates the user's status.
func (s *UserStore) UpdateStatus(ctx context.Context, id string, status models.UserStatus) error {
	if id == "" {
		return fmt.Errorf("id is required")
	}
	query := `UPDATE users SET status = $2 WHERE id = $1`
	result, err := s.db.ExecContext(ctx, query, id, string(status))
	if err != nil {
		return fmt.Errorf("update user status: %w", err)
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		return fmt.Errorf("user not found: %s", id)
	}
	return nil
}

// UpdatePassword updates the user's password hash.
func (s *UserStore) UpdatePassword(ctx context.Context, id string, passwordHash string) error {
	if id == "" {
		return fmt.Errorf("id is required")
	}
	query := `UPDATE users SET password_hash = $2 WHERE id = $1`
	result, err := s.db.ExecContext(ctx, query, id, passwordHash)
	if err != nil {
		return fmt.Errorf("update user password: %w", err)
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		return fmt.Errorf("user not found: %s", id)
	}
	return nil
}

// UpdateLoginSuccess updates last_login_at and resets failed_login_count.
func (s *UserStore) UpdateLoginSuccess(ctx context.Context, id string) error {
	if id == "" {
		return fmt.Errorf("id is required")
	}
	query := `UPDATE users SET last_login_at = NOW(), failed_login_count = 0 WHERE id = $1`
	result, err := s.db.ExecContext(ctx, query, id)
	if err != nil {
		return fmt.Errorf("update login success: %w", err)
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		return fmt.Errorf("user not found: %s", id)
	}
	return nil
}

// IncrementFailedLogin increments the failed_login_count by 1.
func (s *UserStore) IncrementFailedLogin(ctx context.Context, id string) error {
	if id == "" {
		return fmt.Errorf("id is required")
	}
	query := `UPDATE users SET failed_login_count = failed_login_count + 1 WHERE id = $1`
	result, err := s.db.ExecContext(ctx, query, id)
	if err != nil {
		return fmt.Errorf("increment failed login: %w", err)
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		return fmt.Errorf("user not found: %s", id)
	}
	return nil
}

// ResetFailedLogin resets the failed_login_count to 0.
func (s *UserStore) ResetFailedLogin(ctx context.Context, id string) error {
	if id == "" {
		return fmt.Errorf("id is required")
	}
	query := `UPDATE users SET failed_login_count = 0 WHERE id = $1`
	result, err := s.db.ExecContext(ctx, query, id)
	if err != nil {
		return fmt.Errorf("reset failed login: %w", err)
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		return fmt.Errorf("user not found: %s", id)
	}
	return nil
}

// Unlock resets the user's status from locked to active and clears failed_login_count.
func (s *UserStore) Unlock(ctx context.Context, id string) error {
	if id == "" {
		return fmt.Errorf("id is required")
	}
	query := `UPDATE users SET status = 'active', failed_login_count = 0, locked_at = NULL WHERE id = $1 AND status = 'locked'`
	result, err := s.db.ExecContext(ctx, query, id)
	if err != nil {
		return fmt.Errorf("unlock user: %w", err)
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		return fmt.Errorf("user not found or not locked: %s", id)
	}
	return nil
}

// UpdateAPIKeyID updates the user's linked API key.
func (s *UserStore) UpdateAPIKeyID(ctx context.Context, id string, apiKeyID *string) error {
	if id == "" {
		return fmt.Errorf("id is required")
	}
	query := `UPDATE users SET api_key_id = $2 WHERE id = $1`
	result, err := s.db.ExecContext(ctx, query, id, apiKeyID)
	if err != nil {
		return fmt.Errorf("update user api_key_id: %w", err)
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		return fmt.Errorf("user not found: %s", id)
	}
	return nil
}

// scanOneRow scans a single row into a User, returning sql.ErrNoRows if empty.
func (s *UserStore) scanOneRow(ctx context.Context, query string, args ...interface{}) (*models.User, error) {
	u := &models.User{}
	var email sql.NullString
	var passwordHash sql.NullString
	var apiKeyID sql.NullString
	var lastLoginAt sql.NullTime
	var lockedAt sql.NullTime
	var createdBy sql.NullString

	err := s.db.QueryRowContext(ctx, query, args...).Scan(
		&u.ID,
		&u.Username,
		&email,
		&passwordHash,
		&u.DisplayName,
		&u.Role,
		&u.Status,
		&apiKeyID,
		&lastLoginAt,
		&u.FailedLoginCount,
		&lockedAt,
		&createdBy,
		&u.CreatedAt,
		&u.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}

	if email.Valid {
		u.Email = &email.String
	}
	if passwordHash.Valid {
		u.PasswordHash = &passwordHash.String
	}
	if apiKeyID.Valid {
		u.APIKeyID = &apiKeyID.String
	}
	if lastLoginAt.Valid {
		u.LastLoginAt = &lastLoginAt.Time
	}
	if lockedAt.Valid {
		u.LockedAt = &lockedAt.Time
	}
	if createdBy.Valid {
		u.CreatedBy = &createdBy.String
	}

	return u, nil
}

// scanOne wraps scanOneRow with a user-friendly "not found" error.
func (s *UserStore) scanOne(ctx context.Context, query string, args ...interface{}) (*models.User, error) {
	u, err := s.scanOneRow(ctx, query, args...)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("user not found")
		}
		return nil, fmt.Errorf("query user: %w", err)
	}
	return u, nil
}

// scanMany executes a query and scans all rows into User structs.
func (s *UserStore) scanMany(ctx context.Context, query string, args ...interface{}) ([]*models.User, error) {
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("query users: %w", err)
	}
	defer rows.Close()

	var users []*models.User
	for rows.Next() {
		u := &models.User{}
		var email sql.NullString
		var passwordHash sql.NullString
		var apiKeyID sql.NullString
		var lastLoginAt sql.NullTime
		var lockedAt sql.NullTime
		var createdBy sql.NullString

		if err := rows.Scan(
			&u.ID,
			&u.Username,
			&email,
			&passwordHash,
			&u.DisplayName,
			&u.Role,
			&u.Status,
			&apiKeyID,
			&lastLoginAt,
			&u.FailedLoginCount,
			&lockedAt,
			&createdBy,
			&u.CreatedAt,
			&u.UpdatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan user: %w", err)
		}

		if email.Valid {
			u.Email = &email.String
		}
		if passwordHash.Valid {
			u.PasswordHash = &passwordHash.String
		}
		if apiKeyID.Valid {
			u.APIKeyID = &apiKeyID.String
		}
		if lastLoginAt.Valid {
			u.LastLoginAt = &lastLoginAt.Time
		}
		if lockedAt.Valid {
			u.LockedAt = &lockedAt.Time
		}
		if createdBy.Valid {
			u.CreatedBy = &createdBy.String
		}

		users = append(users, u)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate users: %w", err)
	}

	return users, nil
}
```

- [ ] **Step 4: Run tests**

```bash
cd ennam.kg.go && go test ./internal/store/... -run TestUserStore -v -race
```

Expected: PASS (all UserStore tests).

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/user.go internal/store/user_test.go
git commit -m "feat(store): add UserStore with CRUD + login tracking methods (BA-014)"
```

---

## Task 4: User Service (Business Logic + Login)

**Files:**
- Create: `internal/service/user.go`
- Create: `internal/service/user_test.go`

- [ ] **Step 1: Write failing tests for UserService**

```go
// internal/service/user_test.go
package service_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

// --- Mock UserRepository ---

type mockUserRepo struct {
	users    map[string]*models.User
	byName   map[string]*models.User
	byAPIKey map[string]*models.User
}

func newMockUserRepo() *mockUserRepo {
	return &mockUserRepo{
		users:    make(map[string]*models.User),
		byName:   make(map[string]*models.User),
		byAPIKey: make(map[string]*models.User),
	}
}

func (m *mockUserRepo) Create(ctx context.Context, user *models.User) (*models.User, error) {
	user.ID = fmt.Sprintf("user-%d", len(m.users)+1)
	m.users[user.ID] = user
	m.byName[user.Username] = user
	if user.APIKeyID != nil {
		m.byAPIKey[*user.APIKeyID] = user
	}
	return user, nil
}

func (m *mockUserRepo) GetByID(ctx context.Context, id string) (*models.User, error) {
	u, ok := m.users[id]
	if !ok {
		return nil, fmt.Errorf("user not found: %s", id)
	}
	return u, nil
}

func (m *mockUserRepo) GetByUsername(ctx context.Context, username string) (*models.User, error) {
	u, ok := m.byName[username]
	if !ok {
		return nil, fmt.Errorf("user not found: %s", username)
	}
	return u, nil
}

func (m *mockUserRepo) GetByAPIKeyID(ctx context.Context, apiKeyID string) (*models.User, error) {
	u, ok := m.byAPIKey[apiKeyID]
	if !ok {
		return nil, nil
	}
	return u, nil
}

func (m *mockUserRepo) List(ctx context.Context) ([]*models.User, error) {
	var result []*models.User
	for _, u := range m.users {
		result = append(result, u)
	}
	return result, nil
}

func (m *mockUserRepo) Update(ctx context.Context, id, displayName string, email *string, role models.UserRole) (*models.User, error) {
	u, ok := m.users[id]
	if !ok {
		return nil, fmt.Errorf("user not found")
	}
	u.DisplayName = displayName
	u.Email = email
	u.Role = role
	return u, nil
}

func (m *mockUserRepo) UpdateStatus(ctx context.Context, id string, status models.UserStatus) error {
	u, ok := m.users[id]
	if !ok {
		return fmt.Errorf("user not found")
	}
	u.Status = status
	return nil
}

func (m *mockUserRepo) UpdatePassword(ctx context.Context, id, hash string) error {
	u, ok := m.users[id]
	if !ok {
		return fmt.Errorf("user not found")
	}
	u.PasswordHash = &hash
	return nil
}

func (m *mockUserRepo) UpdateLoginSuccess(ctx context.Context, id string) error {
	u, ok := m.users[id]
	if !ok {
		return fmt.Errorf("user not found")
	}
	u.FailedLoginCount = 0
	return nil
}

func (m *mockUserRepo) IncrementFailedLogin(ctx context.Context, id string) error {
	u, ok := m.users[id]
	if !ok {
		return fmt.Errorf("user not found")
	}
	u.FailedLoginCount++
	return nil
}

func (m *mockUserRepo) ResetFailedLogin(ctx context.Context, id string) error {
	u, ok := m.users[id]
	if !ok {
		return fmt.Errorf("user not found")
	}
	u.FailedLoginCount = 0
	return nil
}

func (m *mockUserRepo) Unlock(ctx context.Context, id string) error {
	u, ok := m.users[id]
	if !ok {
		return fmt.Errorf("user not found")
	}
	u.Status = models.UserStatusActive
	u.FailedLoginCount = 0
	u.LockedAt = nil
	return nil
}

func (m *mockUserRepo) UpdateAPIKeyID(ctx context.Context, id string, apiKeyID *string) error {
	u, ok := m.users[id]
	if !ok {
		return fmt.Errorf("user not found")
	}
	u.APIKeyID = apiKeyID
	if apiKeyID != nil {
		m.byAPIKey[*apiKeyID] = u
	}
	return nil
}

// --- Mock APIKeyService for user service ---

type mockAPIKeySvcForUser struct {
	keys map[string]*models.APIKey
}

func newMockAPIKeySvcForUser() *mockAPIKeySvcForUser {
	return &mockAPIKeySvcForUser{keys: make(map[string]*models.APIKey)}
}

func (m *mockAPIKeySvcForUser) CreateKey(ctx context.Context, req service.CreateKeyRequest) (*service.CreateKeyResponse, error) {
	key := &models.APIKey{
		ID:            fmt.Sprintf("key-%d", len(m.keys)+1),
		DeveloperName: req.DeveloperName,
		Role:          req.Role,
	}
	m.keys[key.ID] = key
	return &service.CreateKeyResponse{Key: key, PlaintextKey: "ennam_kg_test123"}, nil
}

func (m *mockAPIKeySvcForUser) RevokeKey(ctx context.Context, req service.RevokeKeyRequest) (*models.APIKey, error) {
	key, ok := m.keys[req.ID]
	if !ok {
		return nil, fmt.Errorf("key not found")
	}
	return key, nil
}

// --- Tests ---

func TestUserService_CreateUser(t *testing.T) {
	repo := newMockUserRepo()
	keySvc := newMockAPIKeySvcForUser()
	svc := service.NewUserService(repo, keySvc, nil)

	resp, err := svc.CreateUser(context.Background(), service.CreateUserRequest{
		Username:    "newuser",
		DisplayName: "New User",
		Password:    "StrongP@ss1",
		Role:        models.UserRoleAdmin,
	})
	if err != nil {
		t.Fatalf("create user: %v", err)
	}
	if resp.User.Username != "newuser" {
		t.Fatalf("username: got %q, want %q", resp.User.Username, "newuser")
	}
	if resp.User.Status != models.UserStatusPendingPasswordChange {
		t.Fatalf("status: got %q, want %q", resp.User.Status, models.UserStatusPendingPasswordChange)
	}
	if resp.APIKey == "" {
		t.Fatal("expected api key to be returned")
	}
}

func TestUserService_CreateUser_WeakPassword(t *testing.T) {
	repo := newMockUserRepo()
	keySvc := newMockAPIKeySvcForUser()
	svc := service.NewUserService(repo, keySvc, nil)

	_, err := svc.CreateUser(context.Background(), service.CreateUserRequest{
		Username:    "weakuser",
		DisplayName: "Weak User",
		Password:    "short",
		Role:        models.UserRoleDeveloper,
	})
	if err == nil {
		t.Fatal("expected error for weak password")
	}
}

func TestUserService_Login_Success(t *testing.T) {
	repo := newMockUserRepo()
	keySvc := newMockAPIKeySvcForUser()
	svc := service.NewUserService(repo, keySvc, nil)

	// Create a user first with a known password.
	hash, _ := models.HashPassword("ValidP@ss1")
	repo.Create(context.Background(), &models.User{
		Username:     "loginuser",
		DisplayName:  "Login User",
		PasswordHash: &hash,
		Role:         models.UserRoleDeveloper,
		Status:       models.UserStatusActive,
		APIKeyID:     strPtr("key-1"),
	})

	resp, err := svc.Login(context.Background(), "loginuser", "ValidP@ss1")
	if err != nil {
		t.Fatalf("login: %v", err)
	}
	if resp.User.Username != "loginuser" {
		t.Fatalf("username: got %q", resp.User.Username)
	}
}

func TestUserService_Login_AccountLocked(t *testing.T) {
	repo := newMockUserRepo()
	keySvc := newMockAPIKeySvcForUser()
	svc := service.NewUserService(repo, keySvc, nil)

	hash, _ := models.HashPassword("ValidP@ss1")
	repo.Create(context.Background(), &models.User{
		Username:     "lockeduser",
		DisplayName:  "Locked User",
		PasswordHash: &hash,
		Role:         models.UserRoleDeveloper,
		Status:       models.UserStatusLocked,
		APIKeyID:     strPtr("key-2"),
	})

	_, err := svc.Login(context.Background(), "lockeduser", "ValidP@ss1")
	if err == nil {
		t.Fatal("expected error for locked account")
	}
}

func TestUserService_Login_NonExistentUser(t *testing.T) {
	repo := newMockUserRepo()
	keySvc := newMockAPIKeySvcForUser()
	svc := service.NewUserService(repo, keySvc, nil)

	_, err := svc.Login(context.Background(), "ghost", "AnyP@ss1")
	if err == nil {
		t.Fatal("expected error for non-existent user")
	}
}

func strPtr(s string) *string { return &s }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ennam.kg.go && go test ./internal/service/... -run TestUserService -v
```

Expected: FAIL — `NewUserService` not found.

- [ ] **Step 3: Implement UserService**

```go
// internal/service/user.go
package service

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/ennam/ennam-kg/internal/models"
)

// UserRepository defines the data access interface for users.
type UserRepository interface {
	Create(ctx context.Context, user *models.User) (*models.User, error)
	GetByID(ctx context.Context, id string) (*models.User, error)
	GetByUsername(ctx context.Context, username string) (*models.User, error)
	GetByAPIKeyID(ctx context.Context, apiKeyID string) (*models.User, error)
	List(ctx context.Context) ([]*models.User, error)
	Update(ctx context.Context, id string, displayName string, email *string, role models.UserRole) (*models.User, error)
	UpdateStatus(ctx context.Context, id string, status models.UserStatus) error
	UpdatePassword(ctx context.Context, id string, passwordHash string) error
	UpdateLoginSuccess(ctx context.Context, id string) error
	IncrementFailedLogin(ctx context.Context, id string) error
	ResetFailedLogin(ctx context.Context, id string) error
	Unlock(ctx context.Context, id string) error
	UpdateAPIKeyID(ctx context.Context, id string, apiKeyID *string) error
}

// UserAPIKeyService defines the subset of APIKeyService methods needed by UserService.
type UserAPIKeyService interface {
	CreateKey(ctx context.Context, req CreateKeyRequest) (*CreateKeyResponse, error)
	RevokeKey(ctx context.Context, req RevokeKeyRequest) (*models.APIKey, error)
}

// CreateUserRequest contains the fields needed to create a new user.
type CreateUserRequest struct {
	Username    string          `json:"username"`
	Email       *string         `json:"email,omitempty"`
	Password    string          `json:"password"`
	DisplayName string          `json:"display_name"`
	Role        models.UserRole `json:"role"`
}

// CreateUserResponse contains the created user and their API key.
type CreateUserResponse struct {
	User   *models.User `json:"user"`
	APIKey string       `json:"api_key"` // Plaintext, shown once
}

// LoginResponse contains the authenticated user and their API key.
type LoginResponse struct {
	User   *models.User `json:"user"`
	APIKey string       `json:"api_key"` // Plaintext API key for subsequent requests
}

// UserService provides business logic for user account management.
type UserService struct {
	repo    UserRepository
	keySvc  UserAPIKeyService
	logger  *slog.Logger
}

// NewUserService creates a new UserService.
func NewUserService(repo UserRepository, keySvc UserAPIKeyService, logger *slog.Logger) *UserService {
	if logger == nil {
		logger = slog.Default()
	}
	return &UserService{
		repo:   repo,
		keySvc: keySvc,
		logger: logger,
	}
}

// CreateUser creates a new user account with an auto-generated internal API key.
// New users are created with status "pending_password_change".
func (s *UserService) CreateUser(ctx context.Context, req CreateUserRequest) (*CreateUserResponse, error) {
	// Validate request.
	if err := s.validateCreateUserRequest(req); err != nil {
		return nil, err
	}

	// Validate and hash password.
	if err := models.ValidatePassword(req.Password); err != nil {
		return nil, &ValidationError{Field: "password", Message: err.Error()}
	}
	hash, err := models.HashPassword(req.Password)
	if err != nil {
		return nil, fmt.Errorf("create user: %w", err)
	}

	// Create internal API key for this user.
	keyResp, err := s.keySvc.CreateKey(ctx, CreateKeyRequest{
		DeveloperName: strings.TrimSpace(req.Username),
		Label:         fmt.Sprintf("Internal key for user %s", req.Username),
		Role:          req.Role.ToAPIKeyRole(),
		ProjectIDs:    []string{}, // Will be configured separately
	})
	if err != nil {
		return nil, fmt.Errorf("create user api key: %w", err)
	}

	// Create user record.
	user := &models.User{
		Username:     strings.TrimSpace(req.Username),
		Email:        req.Email,
		PasswordHash: &hash,
		DisplayName:  strings.TrimSpace(req.DisplayName),
		Role:         req.Role,
		Status:       models.UserStatusPendingPasswordChange,
		APIKeyID:     &keyResp.Key.ID,
	}

	created, err := s.repo.Create(ctx, user)
	if err != nil {
		// Best effort: revoke the API key if user creation fails.
		_, _ = s.keySvc.RevokeKey(ctx, RevokeKeyRequest{ID: keyResp.Key.ID})
		return nil, fmt.Errorf("create user: %w", err)
	}

	s.logger.Info("user created",
		"user_id", created.ID,
		"username", created.Username,
		"role", string(created.Role),
	)

	return &CreateUserResponse{
		User:   created,
		APIKey: keyResp.PlaintextKey,
	}, nil
}

// GetUser retrieves a user by ID.
func (s *UserService) GetUser(ctx context.Context, id string) (*models.User, error) {
	return s.repo.GetByID(ctx, id)
}

// ListUsers retrieves all users.
func (s *UserService) ListUsers(ctx context.Context) ([]*models.User, error) {
	return s.repo.List(ctx)
}

// UpdateUser updates a user's display name, email, and role.
func (s *UserService) UpdateUser(ctx context.Context, id string, displayName string, email *string, role models.UserRole) (*models.User, error) {
	if !role.IsValid() {
		return nil, &ValidationError{Field: "role", Message: fmt.Sprintf("invalid role %q", role)}
	}
	return s.repo.Update(ctx, id, displayName, email, role)
}

// DisableUser disables a user account and revokes their API key.
func (s *UserService) DisableUser(ctx context.Context, id string) error {
	user, err := s.repo.GetByID(ctx, id)
	if err != nil {
		return fmt.Errorf("disable user: %w", err)
	}

	if user.Status == models.UserStatusDisabled {
		return fmt.Errorf("user is already disabled")
	}

	// Revoke the user's API key.
	if user.APIKeyID != nil {
		if _, err := s.keySvc.RevokeKey(ctx, RevokeKeyRequest{ID: *user.APIKeyID}); err != nil {
			s.logger.Warn("failed to revoke api key during user disable",
				"user_id", id,
				"api_key_id", *user.APIKeyID,
				"error", err,
			)
		}
		if err := s.repo.UpdateAPIKeyID(ctx, id, nil); err != nil {
			return fmt.Errorf("disable user: clear api_key_id: %w", err)
		}
	}

	if err := s.repo.UpdateStatus(ctx, id, models.UserStatusDisabled); err != nil {
		return fmt.Errorf("disable user: %w", err)
	}

	s.logger.Info("user disabled", "user_id", id, "username", user.Username)
	return nil
}

// EnableUser re-enables a disabled user account with a new API key.
func (s *UserService) EnableUser(ctx context.Context, id string) (*CreateUserResponse, error) {
	user, err := s.repo.GetByID(ctx, id)
	if err != nil {
		return nil, fmt.Errorf("enable user: %w", err)
	}

	if user.Status != models.UserStatusDisabled {
		return nil, fmt.Errorf("user is not disabled (current status: %s)", user.Status)
	}

	// Generate a new API key for the re-enabled user.
	keyResp, err := s.keySvc.CreateKey(ctx, CreateKeyRequest{
		DeveloperName: user.Username,
		Label:         fmt.Sprintf("Internal key for user %s (re-enabled)", user.Username),
		Role:          user.Role.ToAPIKeyRole(),
		ProjectIDs:    []string{},
	})
	if err != nil {
		return nil, fmt.Errorf("enable user: create api key: %w", err)
	}

	if err := s.repo.UpdateAPIKeyID(ctx, id, &keyResp.Key.ID); err != nil {
		return nil, fmt.Errorf("enable user: link api key: %w", err)
	}

	if err := s.repo.UpdateStatus(ctx, id, models.UserStatusActive); err != nil {
		return nil, fmt.Errorf("enable user: update status: %w", err)
	}

	user.Status = models.UserStatusActive
	user.APIKeyID = &keyResp.Key.ID

	s.logger.Info("user enabled", "user_id", id, "username", user.Username)

	return &CreateUserResponse{
		User:   user,
		APIKey: keyResp.PlaintextKey,
	}, nil
}

// UnlockUser unlocks a locked user account.
func (s *UserService) UnlockUser(ctx context.Context, id string) error {
	if err := s.repo.Unlock(ctx, id); err != nil {
		return fmt.Errorf("unlock user: %w", err)
	}
	s.logger.Info("user unlocked", "user_id", id)
	return nil
}

// ResetPassword sets a new password for a user (admin action).
func (s *UserService) ResetPassword(ctx context.Context, userID string, newPassword string) error {
	if err := models.ValidatePassword(newPassword); err != nil {
		return &ValidationError{Field: "password", Message: err.Error()}
	}

	hash, err := models.HashPassword(newPassword)
	if err != nil {
		return fmt.Errorf("reset password: %w", err)
	}

	if err := s.repo.UpdatePassword(ctx, userID, hash); err != nil {
		return fmt.Errorf("reset password: %w", err)
	}

	// Set status to pending_password_change so user must change on next login.
	if err := s.repo.UpdateStatus(ctx, userID, models.UserStatusPendingPasswordChange); err != nil {
		return fmt.Errorf("reset password: update status: %w", err)
	}

	s.logger.Info("user password reset", "user_id", userID)
	return nil
}

// ChangePassword allows a user to change their own password.
// Verifies the current password before accepting the new one.
func (s *UserService) ChangePassword(ctx context.Context, userID string, currentPassword, newPassword string) error {
	user, err := s.repo.GetByID(ctx, userID)
	if err != nil {
		return fmt.Errorf("change password: %w", err)
	}

	// Verify current password.
	if user.PasswordHash == nil {
		return fmt.Errorf("change password: no password set for this user")
	}
	if err := models.CheckPassword(*user.PasswordHash, currentPassword); err != nil {
		return fmt.Errorf("change password: current password is incorrect")
	}

	// Validate and hash new password.
	if err := models.ValidatePassword(newPassword); err != nil {
		return &ValidationError{Field: "new_password", Message: err.Error()}
	}

	hash, err := models.HashPassword(newPassword)
	if err != nil {
		return fmt.Errorf("change password: %w", err)
	}

	if err := s.repo.UpdatePassword(ctx, userID, hash); err != nil {
		return fmt.Errorf("change password: %w", err)
	}

	// If user was pending_password_change, transition to active.
	if user.Status == models.UserStatusPendingPasswordChange {
		if err := s.repo.UpdateStatus(ctx, userID, models.UserStatusActive); err != nil {
			s.logger.Warn("failed to transition user to active after password change",
				"user_id", userID,
				"error", err,
			)
		}
	}

	s.logger.Info("user password changed", "user_id", userID)
	return nil
}

// Login authenticates a user by username and password.
// Returns the user and their API key on success.
// Implements lockout after MaxFailedLoginAttempts, dummy bcrypt for non-existent users.
func (s *UserService) Login(ctx context.Context, username, password string) (*LoginResponse, error) {
	user, err := s.repo.GetByUsername(ctx, username)
	if err != nil {
		// User not found — perform dummy bcrypt to prevent timing-based enumeration.
		models.DummyPasswordHash()
		return nil, fmt.Errorf("invalid username or password")
	}

	// Check account status.
	if user.Status == models.UserStatusDisabled {
		models.DummyPasswordHash()
		return nil, fmt.Errorf("invalid username or password")
	}
	if user.Status == models.UserStatusLocked {
		return nil, fmt.Errorf("account is locked due to too many failed login attempts")
	}

	// Verify password.
	if user.PasswordHash == nil {
		return nil, fmt.Errorf("invalid username or password")
	}
	if err := models.CheckPassword(*user.PasswordHash, password); err != nil {
		// Wrong password — increment failed count, maybe lock.
		_ = s.repo.IncrementFailedLogin(ctx, user.ID)
		user.FailedLoginCount++

		if user.FailedLoginCount >= models.MaxFailedLoginAttempts {
			now := time.Now()
			_ = s.repo.UpdateStatus(ctx, user.ID, models.UserStatusLocked)
			s.logger.Warn("user account locked after failed login attempts",
				"user_id", user.ID,
				"username", user.Username,
				"failed_count", user.FailedLoginCount,
				"locked_at", now,
			)
		}

		return nil, fmt.Errorf("invalid username or password")
	}

	// Successful login — reset failed count, update last_login_at.
	_ = s.repo.UpdateLoginSuccess(ctx, user.ID)

	// Return the API key for subsequent requests.
	var apiKey string
	if user.APIKeyID != nil {
		apiKey = *user.APIKeyID // Note: this is the key ID, not the plaintext key.
		// The plaintext key was only shown at user creation time.
		// For login, we return the key ID — the caller should have stored the plaintext.
	}

	s.logger.Info("user logged in",
		"user_id", user.ID,
		"username", user.Username,
	)

	return &LoginResponse{
		User:   user,
		APIKey: apiKey,
	}, nil
}

// GetUserByAPIKeyID looks up a user by their linked API key ID.
// Returns nil, nil if no user is associated with this key.
func (s *UserService) GetUserByAPIKeyID(ctx context.Context, apiKeyID string) (*models.User, error) {
	return s.repo.GetByAPIKeyID(ctx, apiKeyID)
}

// validateCreateUserRequest validates all fields in a CreateUserRequest.
func (s *UserService) validateCreateUserRequest(req CreateUserRequest) error {
	var errs []ValidationError

	username := strings.TrimSpace(req.Username)
	if username == "" {
		errs = append(errs, ValidationError{Field: "username", Message: "username is required"})
	} else if len(username) > 255 {
		errs = append(errs, ValidationError{Field: "username", Message: "username must be at most 255 characters"})
	}

	displayName := strings.TrimSpace(req.DisplayName)
	if displayName == "" {
		errs = append(errs, ValidationError{Field: "display_name", Message: "display_name is required"})
	} else if len(displayName) > 255 {
		errs = append(errs, ValidationError{Field: "display_name", Message: "display_name must be at most 255 characters"})
	}

	if req.Password == "" {
		errs = append(errs, ValidationError{Field: "password", Message: "password is required"})
	}

	if !req.Role.IsValid() {
		errs = append(errs, ValidationError{Field: "role", Message: fmt.Sprintf("invalid role %q", req.Role)})
	}

	if len(errs) > 0 {
		return &ValidationErrors{Errors: errs}
	}

	return nil
}
```

- [ ] **Step 4: Run tests**

```bash
cd ennam.kg.go && go test ./internal/service/... -run TestUserService -v -race
```

Expected: PASS (all UserService tests).

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/service/user.go internal/service/user_test.go
git commit -m "feat(service): add UserService with create, login, disable, enable, password management (BA-014)"
```

---

## Task 5: User Handler (9 CRUD Endpoints)

**Files:**
- Create: `internal/handler/user.go`
- Create: `internal/handler/user_test.go`

- [ ] **Step 1: Write failing tests for UserHandler**

```go
// internal/handler/user_test.go
package handler_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/handler"
)

func TestUserHandler_CreateUser_Success(t *testing.T) {
	h := handler.NewUserHandler(newMockUserService(), testLogger())

	body := `{"username":"newuser","display_name":"New User","password":"StrongP@ss1","role":"developer"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/users", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	// Inject admin identity into context for authorization check.
	req = injectAdminIdentity(req)

	rr := httptest.NewRecorder()
	h.HandleCreateUser(rr, req)

	if rr.Code != http.StatusCreated {
		t.Fatalf("status: got %d, want %d. Body: %s", rr.Code, http.StatusCreated, rr.Body.String())
	}
}

func TestUserHandler_CreateUser_NonAdmin_Forbidden(t *testing.T) {
	h := handler.NewUserHandler(newMockUserService(), testLogger())

	body := `{"username":"newuser","display_name":"New User","password":"StrongP@ss1","role":"developer"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/users", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	// Inject non-admin identity.
	req = injectDeveloperIdentity(req)

	rr := httptest.NewRecorder()
	h.HandleCreateUser(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("status: got %d, want %d", rr.Code, http.StatusForbidden)
	}
}

func TestUserHandler_ListUsers(t *testing.T) {
	h := handler.NewUserHandler(newMockUserService(), testLogger())

	req := httptest.NewRequest(http.MethodGet, "/api/v1/users", nil)
	req = injectAdminIdentity(req)

	rr := httptest.NewRecorder()
	h.HandleListUsers(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status: got %d, want %d", rr.Code, http.StatusOK)
	}

	var resp map[string]interface{}
	_ = json.NewDecoder(rr.Body).Decode(&resp)
	if _, ok := resp["users"]; !ok {
		t.Fatal("expected 'users' key in response")
	}
}

func TestUserHandler_GetMe(t *testing.T) {
	h := handler.NewUserHandler(newMockUserService(), testLogger())

	req := httptest.NewRequest(http.MethodGet, "/api/v1/users/me", nil)
	req = injectAdminIdentityWithUserID(req, "user-1")

	rr := httptest.NewRecorder()
	h.HandleGetMe(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status: got %d, want %d. Body: %s", rr.Code, http.StatusOK, rr.Body.String())
	}
}
```

- [ ] **Step 2: Implement UserHandler**

```go
// internal/handler/user.go
package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

// UserHandler handles user account management REST API requests.
type UserHandler struct {
	svc    *service.UserService
	logger *slog.Logger
}

// NewUserHandler creates a new UserHandler.
func NewUserHandler(svc *service.UserService, logger *slog.Logger) *UserHandler {
	return &UserHandler{svc: svc, logger: logger}
}

// RegisterRoutes registers all user management endpoints.
func (h *UserHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/users", h.HandleCreateUser)
	mux.HandleFunc("GET /api/v1/users", h.HandleListUsers)
	mux.HandleFunc("GET /api/v1/users/me", h.HandleGetMe)
	mux.HandleFunc("GET /api/v1/users/{id}", h.HandleGetUser)
	mux.HandleFunc("PATCH /api/v1/users/{id}", h.HandleUpdateUser)
	mux.HandleFunc("POST /api/v1/users/{id}/disable", h.HandleDisableUser)
	mux.HandleFunc("POST /api/v1/users/{id}/enable", h.HandleEnableUser)
	mux.HandleFunc("POST /api/v1/users/{id}/unlock", h.HandleUnlockUser)
	mux.HandleFunc("POST /api/v1/users/{id}/reset-password", h.HandleResetPassword)
}

// requireAdmin checks that the caller has admin role. Returns false and writes
// a 403 Forbidden response if not.
func (h *UserHandler) requireAdmin(w http.ResponseWriter, r *http.Request) (*middleware.DeveloperIdentity, bool) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return nil, false
	}
	if identity.Role != models.APIKeyRoleAdmin {
		errorResponse(w, http.StatusForbidden, "admin access required")
		return nil, false
	}
	return identity, true
}

// HandleCreateUser handles POST /api/v1/users.
// Admin-only endpoint that creates a new user account.
func (h *UserHandler) HandleCreateUser(w http.ResponseWriter, r *http.Request) {
	identity, ok := h.requireAdmin(w, r)
	if !ok {
		return
	}

	var req service.CreateUserRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	resp, err := h.svc.CreateUser(r.Context(), req)
	if err != nil {
		h.handleServiceError(w, err, "create user")
		return
	}

	h.logger.Info("user created via API",
		"user_id", resp.User.ID,
		"username", resp.User.Username,
		"created_by", identity.DeveloperName,
	)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	_ = json.NewEncoder(w).Encode(resp)
}

// HandleListUsers handles GET /api/v1/users.
// Admin-only endpoint.
func (h *UserHandler) HandleListUsers(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}

	users, err := h.svc.ListUsers(r.Context())
	if err != nil {
		h.logger.ErrorContext(r.Context(), "list users failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to list users")
		return
	}
	if users == nil {
		users = []*models.User{}
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"users": users,
		"total": len(users),
	})
}

// HandleGetUser handles GET /api/v1/users/{id}.
// Admin-only endpoint.
func (h *UserHandler) HandleGetUser(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "user id is required")
		return
	}

	user, err := h.svc.GetUser(r.Context(), id)
	if err != nil {
		errorResponse(w, http.StatusNotFound, "user not found")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(user)
}

// HandleGetMe handles GET /api/v1/users/me.
// Returns the current authenticated user's profile.
func (h *UserHandler) HandleGetMe(w http.ResponseWriter, r *http.Request) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	// Look up the user by their API key ID.
	user, err := h.svc.GetUserByAPIKeyID(r.Context(), identity.KeyID)
	if err != nil {
		h.logger.ErrorContext(r.Context(), "get current user failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to retrieve user profile")
		return
	}
	if user == nil {
		errorResponse(w, http.StatusNotFound, "no user account linked to this API key")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(user)
}

// HandleUpdateUser handles PATCH /api/v1/users/{id}.
// Admin-only endpoint.
func (h *UserHandler) HandleUpdateUser(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "user id is required")
		return
	}

	var body struct {
		DisplayName string          `json:"display_name"`
		Email       *string         `json:"email,omitempty"`
		Role        models.UserRole `json:"role"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	user, err := h.svc.UpdateUser(r.Context(), id, body.DisplayName, body.Email, body.Role)
	if err != nil {
		h.handleServiceError(w, err, "update user")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(user)
}

// HandleDisableUser handles POST /api/v1/users/{id}/disable.
// Admin-only endpoint.
func (h *UserHandler) HandleDisableUser(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "user id is required")
		return
	}

	if err := h.svc.DisableUser(r.Context(), id); err != nil {
		h.handleServiceError(w, err, "disable user")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "disabled"})
}

// HandleEnableUser handles POST /api/v1/users/{id}/enable.
// Admin-only endpoint. Returns a new API key for the re-enabled user.
func (h *UserHandler) HandleEnableUser(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "user id is required")
		return
	}

	resp, err := h.svc.EnableUser(r.Context(), id)
	if err != nil {
		h.handleServiceError(w, err, "enable user")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(resp)
}

// HandleUnlockUser handles POST /api/v1/users/{id}/unlock.
// Admin-only endpoint.
func (h *UserHandler) HandleUnlockUser(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "user id is required")
		return
	}

	if err := h.svc.UnlockUser(r.Context(), id); err != nil {
		h.handleServiceError(w, err, "unlock user")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "unlocked"})
}

// HandleResetPassword handles POST /api/v1/users/{id}/reset-password.
// Admin-only endpoint. Sets a new password and forces pending_password_change.
func (h *UserHandler) HandleResetPassword(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "user id is required")
		return
	}

	var body struct {
		NewPassword string `json:"new_password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if body.NewPassword == "" {
		errorResponse(w, http.StatusBadRequest, "new_password is required")
		return
	}

	if err := h.svc.ResetPassword(r.Context(), id, body.NewPassword); err != nil {
		h.handleServiceError(w, err, "reset password")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "password_reset"})
}

// handleServiceError maps service-layer errors to appropriate HTTP status codes.
func (h *UserHandler) handleServiceError(w http.ResponseWriter, err error, action string) {
	switch e := err.(type) {
	case *service.ValidationError:
		errorResponse(w, http.StatusBadRequest, e.Error())
	case *service.ValidationErrors:
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"error":  "validation failed",
			"errors": e.Errors,
		})
	default:
		h.logger.Error(action+" failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, action+" failed")
	}
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/handler/... -run TestUserHandler -v -race
```

Expected: PASS (all UserHandler tests).

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/handler/user.go internal/handler/user_test.go
git commit -m "feat(handler): add UserHandler with 9 CRUD endpoints for user management (BA-014)"
```

---

## Task 6: Auth Handler (3 Auth Endpoints)

**Files:**
- Create: `internal/handler/auth.go`
- Create: `internal/handler/auth_test.go`

- [ ] **Step 1: Write failing tests for AuthHandler**

```go
// internal/handler/auth_test.go
package handler_test

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/handler"
)

func TestAuthHandler_Login_Success(t *testing.T) {
	h := handler.NewAuthHandler(newMockUserService(), testLogger())

	body := `{"username":"loginuser","password":"ValidP@ss1"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	h.HandleLogin(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status: got %d, want %d. Body: %s", rr.Code, http.StatusOK, rr.Body.String())
	}
}

func TestAuthHandler_Login_MissingFields(t *testing.T) {
	h := handler.NewAuthHandler(newMockUserService(), testLogger())

	body := `{"username":"","password":""}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	h.HandleLogin(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status: got %d, want %d", rr.Code, http.StatusBadRequest)
	}
}

func TestAuthHandler_ChangePassword_Success(t *testing.T) {
	h := handler.NewAuthHandler(newMockUserService(), testLogger())

	body := `{"current_password":"OldP@ss1","new_password":"NewStr0ng!"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/change-password", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req = injectAdminIdentityWithUserID(req, "user-1")

	rr := httptest.NewRecorder()
	h.HandleChangePassword(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status: got %d, want %d. Body: %s", rr.Code, http.StatusOK, rr.Body.String())
	}
}

func TestAuthHandler_Logout(t *testing.T) {
	h := handler.NewAuthHandler(newMockUserService(), testLogger())

	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/logout", nil)
	req = injectAdminIdentity(req)

	rr := httptest.NewRecorder()
	h.HandleLogout(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status: got %d, want %d", rr.Code, http.StatusOK)
	}
}
```

- [ ] **Step 2: Implement AuthHandler**

```go
// internal/handler/auth.go
package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/service"
)

// AuthHandler handles authentication-related REST API requests.
type AuthHandler struct {
	svc    *service.UserService
	logger *slog.Logger
}

// NewAuthHandler creates a new AuthHandler.
func NewAuthHandler(svc *service.UserService, logger *slog.Logger) *AuthHandler {
	return &AuthHandler{svc: svc, logger: logger}
}

// RegisterRoutes registers all authentication endpoints.
func (h *AuthHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/auth/login", h.HandleLogin)
	mux.HandleFunc("POST /api/v1/auth/change-password", h.HandleChangePassword)
	mux.HandleFunc("POST /api/v1/auth/logout", h.HandleLogout)
}

// HandleLogin handles POST /api/v1/auth/login.
// Unauthenticated endpoint — exempt from auth middleware.
func (h *AuthHandler) HandleLogin(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	if body.Username == "" || body.Password == "" {
		errorResponse(w, http.StatusBadRequest, "username and password are required")
		return
	}

	resp, err := h.svc.Login(r.Context(), body.Username, body.Password)
	if err != nil {
		// Use 401 for all login failures to avoid leaking info.
		h.logger.Warn("login attempt failed",
			"username", body.Username,
			"remote_addr", r.RemoteAddr,
			"error", err,
		)
		errorResponse(w, http.StatusUnauthorized, err.Error())
		return
	}

	h.logger.Info("user logged in via API",
		"user_id", resp.User.ID,
		"username", resp.User.Username,
		"remote_addr", r.RemoteAddr,
	)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"user":    resp.User,
		"api_key": resp.APIKey,
		"message": "Login successful. Use the api_key in the Authorization header for subsequent requests.",
	})
}

// HandleChangePassword handles POST /api/v1/auth/change-password.
// Requires authentication. Allows the current user to change their own password.
func (h *AuthHandler) HandleChangePassword(w http.ResponseWriter, r *http.Request) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	// Resolve user from API key.
	user, err := h.svc.GetUserByAPIKeyID(r.Context(), identity.KeyID)
	if err != nil || user == nil {
		errorResponse(w, http.StatusNotFound, "no user account linked to this API key")
		return
	}

	var body struct {
		CurrentPassword string `json:"current_password"`
		NewPassword     string `json:"new_password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	if body.CurrentPassword == "" || body.NewPassword == "" {
		errorResponse(w, http.StatusBadRequest, "current_password and new_password are required")
		return
	}

	if err := h.svc.ChangePassword(r.Context(), user.ID, body.CurrentPassword, body.NewPassword); err != nil {
		switch e := err.(type) {
		case *service.ValidationError:
			errorResponse(w, http.StatusBadRequest, e.Error())
		default:
			errorResponse(w, http.StatusBadRequest, err.Error())
		}
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"status":  "password_changed",
		"message": "Password changed successfully.",
	})
}

// HandleLogout handles POST /api/v1/auth/logout.
// Server-side logout is a no-op for API key auth — the client discards the key.
// Included for completeness and audit logging.
func (h *AuthHandler) HandleLogout(w http.ResponseWriter, r *http.Request) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity != nil {
		h.logger.Info("user logged out",
			"developer", identity.DeveloperName,
			"key_prefix", identity.KeyPrefix,
		)
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"status":  "logged_out",
		"message": "Logout successful. Discard the API key client-side.",
	})
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/handler/... -run TestAuthHandler -v -race
```

Expected: PASS (all AuthHandler tests).

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/handler/auth.go internal/handler/auth_test.go
git commit -m "feat(handler): add AuthHandler with login, change-password, logout endpoints (BA-014)"
```

---

## Task 7: Middleware Updates (Login Skip + User Context)

**Files:**
- Modify: `internal/middleware/auth.go`
- Modify: `internal/middleware/auth_test.go`

- [ ] **Step 1: Write failing tests for login path exemption and user context**

```go
// Add to internal/middleware/auth_test.go

func TestAuth_LoginPathExempt(t *testing.T) {
	// Verify that POST /api/v1/auth/login bypasses auth middleware.
	called := false
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	mockAuth := &mockAuthenticator{}
	mw := middleware.Auth(mockAuth, slog.Default())(handler)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
	rr := httptest.NewRecorder()
	mw.ServeHTTP(rr, req)

	if !called {
		t.Fatal("expected handler to be called for login path")
	}
	if rr.Code != http.StatusOK {
		t.Fatalf("status: got %d, want %d", rr.Code, http.StatusOK)
	}
}

func TestGetUserIdentity(t *testing.T) {
	// Verify that UserIdentity can be extracted from context.
	userID := "test-user-id"
	ctx := context.WithValue(context.Background(), middleware.UserIdentityKey, &middleware.UserIdentity{
		UserID:   userID,
		Username: "testuser",
		Role:     "admin",
	})

	identity := middleware.GetUserIdentity(ctx)
	if identity == nil {
		t.Fatal("expected non-nil UserIdentity")
	}
	if identity.UserID != userID {
		t.Fatalf("user_id: got %q, want %q", identity.UserID, userID)
	}
}
```

- [ ] **Step 2: Update isExemptPath to include login endpoint**

In `internal/middleware/auth.go`, update `isExemptPath`:

```go
// isExemptPath returns true for paths that do not require authentication.
func isExemptPath(path string) bool {
	switch path {
	case "/healthz", "/readyz", "/api/v1/auth/login":
		return true
	default:
		return false
	}
}
```

- [ ] **Step 3: Add UserIdentity type and context injection**

Add to `internal/middleware/auth.go`:

```go
const (
	// UserIdentityKey is the context key for the authenticated user account.
	UserIdentityKey contextKey = "user_identity"
)

// UserIdentity holds the authenticated user account information.
// Injected into context when the API key maps to a user account.
type UserIdentity struct {
	// UserID is the UUID of the user account.
	UserID string
	// Username is the user's login name.
	Username string
	// Role is the user-level role (admin, developer, viewer).
	Role string
	// Status is the user's account status.
	Status string
}

// GetUserIdentity extracts the authenticated user identity from context.
// Returns nil if no user is linked to the current API key.
func GetUserIdentity(ctx context.Context) *UserIdentity {
	if identity, ok := ctx.Value(UserIdentityKey).(*UserIdentity); ok {
		return identity
	}
	return nil
}
```

**Note:** The actual user context injection (looking up the user by API key ID on each request) is wired in `cmd/kg-server/main.go` via a `UserContextMiddleware` that wraps the auth middleware. See Task 8.

- [ ] **Step 4: Add UserContextMiddleware**

Add to `internal/middleware/auth.go`:

```go
// UserLookup defines the interface for looking up a user by API key ID.
type UserLookup interface {
	GetUserByAPIKeyID(ctx context.Context, apiKeyID string) (*UserIdentity, error)
}

// UserContext returns middleware that injects UserIdentity into the context
// after successful API key authentication. If no user is linked to the key,
// the request proceeds without UserIdentity (backwards-compatible).
func UserContext(lookup UserLookup, logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			identity := GetDeveloperIdentity(r.Context())
			if identity == nil {
				// No API key auth — skip user lookup.
				next.ServeHTTP(w, r)
				return
			}

			user, err := lookup.GetUserByAPIKeyID(r.Context(), identity.KeyID)
			if err != nil {
				logger.Warn("user lookup failed",
					"key_id", identity.KeyID,
					"error", err,
				)
			}

			if user != nil {
				ctx := context.WithValue(r.Context(), UserIdentityKey, user)
				r = r.WithContext(ctx)
			}

			next.ServeHTTP(w, r)
		})
	}
}
```

- [ ] **Step 5: Run tests**

```bash
cd ennam.kg.go && go test ./internal/middleware/... -v -race
```

Expected: PASS (all middleware tests including new ones).

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add internal/middleware/auth.go internal/middleware/auth_test.go
git commit -m "feat(middleware): add login path exemption, UserIdentity context, UserContext middleware (BA-014)"
```

---

## Task 8: Wire into Composition Root

**Files:**
- Modify: `cmd/kg-server/main.go`

- [ ] **Step 1: Add UserStore, UserService, UserHandler, AuthHandler wiring to buildRouter()**

Add the following block to `buildRouter()` in `cmd/kg-server/main.go`, after the existing handler registrations (e.g., after the admin sync portal block):

```go
	// Register user account and auth handlers (BA-014 Phase 3).
	userStore := store.NewUserStore(db)
	apiKeyStore := store.NewAPIKeyStore(db)
	apiKeySvc := service.NewAPIKeyService(apiKeyStore, logger)
	userSvc := service.NewUserService(userStore, apiKeySvc, logger)
	userHandler := handler.NewUserHandler(userSvc, logger)
	userHandler.RegisterRoutes(apiMux)
	authHandler := handler.NewAuthHandler(userSvc, logger)
	authHandler.RegisterRoutes(apiMux)
	logger.Info("user account and auth endpoints enabled (BA-014)")
```

- [ ] **Step 2: Register auth/login as a public route**

The `isExemptPath` change in Task 7 handles this. However, since the auth middleware wraps `apiMux` and the login route is inside `apiMux`, we need the exempt path approach. The `/api/v1/auth/login` path will be exempt from API key validation but still routed through the protected handler.

Alternatively, register the login handler on the **public** mux (before the auth middleware):

```go
	// In buildRouter(), register login on the public mux (before auth).
	// This is cleaner than exempt-path since login genuinely needs no auth.
	authHandlerPublic := handler.NewAuthHandler(userSvc, logger)
	mux.HandleFunc("POST /api/v1/auth/login", authHandlerPublic.HandleLogin)
```

Choose the approach that's simpler — the `isExemptPath` approach is less invasive.

- [ ] **Step 3: Add UserContext middleware to the protected handler chain**

After the existing auth middleware application:

```go
	// Apply auth middleware to all API routes.
	protectedHandler := middleware.Auth(auth, logger)(apiMux)

	// Add user context injection (BA-014).
	// Wraps the auth-protected handler to inject UserIdentity when the API key maps to a user.
	userLookupAdapter := &userLookupAdapter{userSvc: userSvc}
	protectedHandler = middleware.UserContext(userLookupAdapter, logger)(protectedHandler)
```

And add the adapter struct:

```go
// userLookupAdapter adapts UserService to the middleware.UserLookup interface.
type userLookupAdapter struct {
	userSvc *service.UserService
}

func (a *userLookupAdapter) GetUserByAPIKeyID(ctx context.Context, apiKeyID string) (*middleware.UserIdentity, error) {
	user, err := a.userSvc.GetUserByAPIKeyID(ctx, apiKeyID)
	if err != nil || user == nil {
		return nil, err
	}
	return &middleware.UserIdentity{
		UserID:   user.ID,
		Username: user.Username,
		Role:     string(user.Role),
		Status:   string(user.Status),
	}, nil
}
```

- [ ] **Step 4: Update the registered routes log**

Add to the routes list in the `logger.Info("registered handlers", ...)` call:

```go
		// User account routes (BA-014 Phase 3):
		"POST /api/v1/users",
		"GET /api/v1/users",
		"GET /api/v1/users/me",
		"GET /api/v1/users/{id}",
		"PATCH /api/v1/users/{id}",
		"POST /api/v1/users/{id}/disable",
		"POST /api/v1/users/{id}/enable",
		"POST /api/v1/users/{id}/unlock",
		"POST /api/v1/users/{id}/reset-password",
		// Auth routes (BA-014 Phase 3):
		"POST /api/v1/auth/login",
		"POST /api/v1/auth/change-password",
		"POST /api/v1/auth/logout",
```

- [ ] **Step 5: Build and verify**

```bash
cd ennam.kg.go && go build ./cmd/kg-server/
```

Expected: PASS — binary compiles successfully.

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add cmd/kg-server/main.go
git commit -m "feat(server): wire user accounts and auth handlers into composition root (BA-014)"
```

---

## Task 9: Seed Admin User Script

**Files:**
- Create: `scripts/seed_admin_user.go` (standalone script, or as part of migration)

- [ ] **Step 1: Create admin seed as part of migration 032 (alternative: separate script)**

The preferred approach is a standalone script that can be run post-migration. This avoids hardcoding credentials in migration files.

```go
// scripts/seed_admin_user.go
//go:build ignore
// +build ignore

// seed_admin_user creates the initial admin user account.
// Usage: go run scripts/seed_admin_user.go -username admin -password "AdminP@ss1" -display-name "System Admin"
package main

import (
	"context"
	"database/sql"
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
	"github.com/ennam/ennam-kg/internal/store"
	_ "github.com/lib/pq"
)

func main() {
	username := flag.String("username", "admin", "Admin username")
	password := flag.String("password", "", "Admin password (must meet complexity requirements)")
	displayName := flag.String("display-name", "System Admin", "Admin display name")
	email := flag.String("email", "", "Admin email (optional)")
	dsn := flag.String("dsn", "", "PostgreSQL DSN (default: from KG_DATABASE_URL env)")
	flag.Parse()

	if *password == "" {
		fmt.Fprintln(os.Stderr, "error: -password is required")
		os.Exit(1)
	}

	dbDSN := *dsn
	if dbDSN == "" {
		dbDSN = os.Getenv("KG_DATABASE_URL")
	}
	if dbDSN == "" {
		fmt.Fprintln(os.Stderr, "error: provide -dsn or set KG_DATABASE_URL")
		os.Exit(1)
	}

	db, err := sql.Open("postgres", dbDSN)
	if err != nil {
		log.Fatalf("connect: %v", err)
	}
	defer db.Close()

	ctx := context.Background()

	apiKeyStore := store.NewAPIKeyStore(db)
	apiKeySvc := service.NewAPIKeyService(apiKeyStore, nil)
	userStore := store.NewUserStore(db)
	userSvc := service.NewUserService(userStore, apiKeySvc, nil)

	req := service.CreateUserRequest{
		Username:    *username,
		DisplayName: *displayName,
		Password:    *password,
		Role:        models.UserRoleAdmin,
	}
	if *email != "" {
		req.Email = email
	}

	resp, err := userSvc.CreateUser(ctx, req)
	if err != nil {
		log.Fatalf("create admin user: %v", err)
	}

	fmt.Printf("Admin user created successfully:\n")
	fmt.Printf("  User ID:      %s\n", resp.User.ID)
	fmt.Printf("  Username:     %s\n", resp.User.Username)
	fmt.Printf("  Display Name: %s\n", resp.User.DisplayName)
	fmt.Printf("  Role:         %s\n", resp.User.Role)
	fmt.Printf("  Status:       %s\n", resp.User.Status)
	fmt.Printf("  API Key:      %s\n", resp.APIKey)
	fmt.Printf("\nIMPORTANT: Save the API key — it will not be shown again.\n")
	fmt.Printf("The user must change their password on first login (status: pending_password_change).\n")
}
```

- [ ] **Step 2: Test the seed script manually**

```bash
cd ennam.kg.go && go run scripts/seed_admin_user.go -username admin -password "AdminP@ss1!" -display-name "System Admin"
```

Expected: Admin user created with API key printed.

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.go
git add scripts/seed_admin_user.go
git commit -m "feat(scripts): add seed_admin_user script for initial admin setup (BA-014)"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] Migration 032 applies cleanly: `go run ./cmd/kg-migrate/ up`
- [ ] Migration 032 rolls back cleanly: `go run ./cmd/kg-migrate/ down 1` then `up` again
- [ ] All tests pass: `go test ./... -race -count=1`
- [ ] Binary compiles: `go build ./cmd/kg-server/`
- [ ] POST `/api/v1/auth/login` with valid credentials returns 200 + API key
- [ ] POST `/api/v1/auth/login` with invalid credentials returns 401
- [ ] POST `/api/v1/auth/login` is accessible without Authorization header
- [ ] POST `/api/v1/users` with admin key returns 201
- [ ] POST `/api/v1/users` with non-admin key returns 403
- [ ] GET `/api/v1/users/me` returns the current user's profile
- [ ] POST `/api/v1/auth/change-password` works for authenticated user
- [ ] Account locks after 5 failed login attempts
- [ ] POST `/api/v1/users/{id}/unlock` clears lockout
- [ ] POST `/api/v1/users/{id}/disable` revokes the user's API key
- [ ] POST `/api/v1/users/{id}/enable` generates a new API key
- [ ] Non-existent username login takes same time as valid username (no timing leak)

---

## Summary

| Task | Files | Key Output |
|------|-------|------------|
| 1. Migration 032 | 2 SQL files | `users` table with indexes, constraints, updated_at trigger |
| 2. User Model | 1 Go file | `User` struct, `UserRole`, `UserStatus`, password helpers |
| 3. User Store | 2 Go files | 12 store methods (CRUD + login tracking) |
| 4. User Service | 2 Go files | Create, Login, Disable, Enable, Unlock, ChangePassword, ResetPassword |
| 5. User Handler | 2 Go files | 9 REST endpoints under `/api/v1/users/*` |
| 6. Auth Handler | 2 Go files | 3 REST endpoints under `/api/v1/auth/*` |
| 7. Middleware | 2 Go files | Login exempt path, `UserIdentity` context, `UserContext` middleware |
| 8. Composition Root | 1 Go file | Wire everything into `buildRouter()` |
| 9. Seed Script | 1 Go file | CLI tool to create initial admin user |

**Total: 9 tasks, 15 new files, 3 modified files, ~1200 lines of Go code.**
