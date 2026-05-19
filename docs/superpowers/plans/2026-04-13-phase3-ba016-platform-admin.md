# BA-016 Platform Administration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Phase 3 Step 3** — Depends on BA-014 (users) + BA-015 (project_members). Working directory: `ennam.kg.go/`

**Goal:** Expose existing API key store/service via REST endpoints, add system_settings with DB-override-over-YAML-fallback, extend audit_trail operations for Phase 2+3, and build activity feed endpoints with actor resolution.

**Architecture:** Follows the existing layered pattern: Handler (HTTP) -> Service (business logic) -> Store (PostgreSQL). Settings service adds an in-memory cache with 60-second refresh. API key handler is a thin wrapper over the existing `APIKeyService`. Activity feed extends `AuditStore` with JOIN queries for display_name resolution.

**Tech Stack:** Go std lib, `database/sql`, `log/slog`, PostgreSQL, JSONB

**BA Reference:** `ennam.kg.requirements/documents/phase3/BA-016-platform-administration.md`

**Prerequisites:** BA-014 (users table), BA-015 (project_members table)

---

## What Already Exists

| Layer | File | What's There |
|-------|------|-------------|
| Store | `internal/store/apikey.go` | Full CRUD: Create, GetByID, GetByKeyHash, ListByDeveloper, ListActive, Revoke, UpdateLastUsed, UpdateLabel, Delete, Count, Authenticate |
| Service | `internal/service/apikey.go` | CreateKey (generates plaintext+hash), RevokeKey, ValidateKey, ListKeys, GetKey, CountKeys |
| Handler | `internal/handler/audit.go` | GET /audit/{id}, GET /audit, GET /audit/history/{type}/{id} |
| Store | `internal/store/audit.go` | RecordAudit, GetAuditEntry, ListAuditEntries, GetEntityHistory |
| Model | `internal/models/audit.go` | AuditEntry, AuditOperation (8 ops: node.*, edge.*, session.*), AuditEntityType (node, edge, session) |
| Config | `internal/config/server.go` | FeatureFlagsConfig (YAML-based, no DB persistence) |
| Middleware | `internal/middleware/auth.go` | DeveloperIdentity in context, GetDeveloperIdentity(), RequireDeveloperIdentity() |

## What's Missing

- **No API key handler** — store+service exist, but no REST endpoints expose them
- **No system_settings table** — feature flags and platform settings are YAML-only
- **No activity feed** — audit_trail has no display_name resolution or membership-scoped queries
- **No activity stats** — no aggregation over audit_trail for dashboard counters
- **Audit operations limited** — only 8 Phase 1 operations, missing sync/auth/user/member/project/setting ops

---

## File Structure

### New Files

```
db/migrations/
├── 000032_create_system_settings.up.sql        # system_settings table + seed
├── 000032_create_system_settings.down.sql
├── 000033_extend_audit_operations.up.sql        # Extend CHECK constraint
├── 000033_extend_audit_operations.down.sql

internal/models/
├── settings.go                                  # SystemSetting model

internal/store/
├── settings.go                                  # SettingsStore CRUD
├── settings_test.go

internal/service/
├── settings.go                                  # SettingsService (cache + DB-over-YAML)
├── settings_test.go

internal/handler/
├── apikey.go                                    # APIKeyHandler (6 endpoints)
├── apikey_test.go
├── settings.go                                  # SettingsHandler (4 endpoints)
├── settings_test.go
├── activity.go                                  # ActivityHandler (2 endpoints)
├── activity_test.go
```

### Modified Files

```
internal/models/audit.go                         # Add new AuditOperation + AuditEntityType constants
internal/store/audit.go                          # Add GetActivityFeed, GetActivityStats methods
internal/store/audit_test.go                     # Tests for new methods
cmd/kg-server/main.go                           # Wire settings store/service/handler, apikey handler, activity handler
```

---

## Task 1: Migration 032 — system_settings table + seed data

- [ ] **Step 1: Create up migration** `db/migrations/000032_create_system_settings.up.sql`

```sql
-- Ennam Knowledge Graph Platform — Migration 000032
-- Create system_settings table for platform configuration with DB persistence

CREATE TABLE IF NOT EXISTS system_settings (
    key         VARCHAR(255) PRIMARY KEY,
    value       JSONB NOT NULL,
    description TEXT,
    category    VARCHAR(100) NOT NULL DEFAULT 'general',
    updated_by  UUID REFERENCES users(id),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT system_settings_category_check
        CHECK (category IN ('ai', 'sync', 'auth', 'feature_flags', 'general'))
);

CREATE INDEX IF NOT EXISTS idx_system_settings_category ON system_settings (category);

-- Seed 12 default settings
INSERT INTO system_settings (key, value, description, category) VALUES
    -- Feature flags (override YAML config when set)
    ('feature_flags.verbose_errors',        'false',                          'Show detailed error messages in API responses',     'feature_flags'),
    ('feature_flags.cross_project_enabled', 'false',                          'Allow cross-project edge creation',                 'feature_flags'),
    ('feature_flags.rate_limiting_enabled', 'true',                           'Enable API rate limiting',                          'feature_flags'),
    ('feature_flags.metrics_enabled',       'true',                           'Enable CloudWatch metrics publishing',              'feature_flags'),

    -- AI settings
    ('ai.max_tokens_per_request',           '4096',                           'Maximum tokens per AI request',                     'ai'),
    ('ai.monthly_budget_usd',              '100.00',                          'Monthly AI spending budget in USD',                 'ai'),
    ('ai.default_provider',                '"auto"',                          'Default AI provider selection strategy',             'ai'),

    -- Sync settings
    ('sync.max_concurrent_jobs',           '3',                               'Maximum concurrent sync jobs',                      'sync'),
    ('sync.job_timeout_minutes',           '30',                              'Sync job timeout in minutes',                       'sync'),
    ('sync.auto_sync_enabled',             'false',                           'Enable automatic periodic sync',                    'sync'),

    -- Auth settings
    ('auth.session_timeout_hours',         '24',                              'User session timeout in hours',                     'auth'),
    ('auth.max_api_keys_per_user',         '10',                              'Maximum API keys per user',                         'auth')
ON CONFLICT (key) DO NOTHING;
```

- [ ] **Step 2: Create down migration** `db/migrations/000032_create_system_settings.down.sql`

```sql
DROP INDEX IF EXISTS idx_system_settings_category;
DROP TABLE IF EXISTS system_settings;
```

- [ ] **Step 3: Run migration and verify**

```bash
cd ennam.kg.go && go run ./cmd/kg-migrate/ up
```

- [ ] **Step 4: Commit**

```bash
git add db/migrations/000032_*
git commit -m "migration(032): create system_settings table with 12 default settings (BA-016)"
```

---

## Task 2: Migration 033 — extend audit_trail operations

The existing audit_trail CHECK constraint only allows 8 Phase 1 operations. Phase 2 and Phase 3 introduce many more operations. We must ALTER the constraint.

- [ ] **Step 1: Create up migration** `db/migrations/000033_extend_audit_operations.up.sql`

```sql
-- Ennam Knowledge Graph Platform — Migration 000033
-- Extend audit_trail operations CHECK for Phase 2 + Phase 3

-- Drop the existing CHECK constraint on operation column
ALTER TABLE audit_trail DROP CONSTRAINT IF EXISTS audit_trail_operation_check;

-- Add expanded CHECK constraint covering Phase 1 + 2 + 3 operations
ALTER TABLE audit_trail ADD CONSTRAINT audit_trail_operation_check
    CHECK (operation IN (
        -- Phase 1: Node/edge/session operations
        'node.create', 'node.update', 'node.deprecate',
        'edge.create', 'edge.delete',
        'session.start', 'session.end', 'session.update',
        -- Phase 2: Sync, KG generation, query, benchmark
        'sync.start', 'sync.complete', 'sync.fail',
        'kg.generate',
        'query.submit',
        'benchmark.run',
        -- Phase 3: Auth operations
        'auth.login', 'auth.login_failed', 'auth.password_change',
        'auth.password_reset', 'auth.logout',
        -- Phase 3: User management
        'user.create', 'user.disable', 'user.enable', 'user.unlock',
        -- Phase 3: Member management
        'member.add', 'member.remove', 'member.role_change',
        -- Phase 3: Project lifecycle
        'project.create', 'project.archive', 'project.unarchive',
        -- Phase 3: Settings
        'setting.update'
    ));

-- Extend entity_type CHECK to include new entity types
ALTER TABLE audit_trail DROP CONSTRAINT IF EXISTS audit_trail_entity_type_check;

ALTER TABLE audit_trail ADD CONSTRAINT audit_trail_entity_type_check
    CHECK (entity_type IN (
        'node', 'edge', 'session',
        'data_source', 'sync_job', 'kg_generation',
        'ai_query', 'benchmark',
        'user', 'member', 'project', 'api_key', 'setting'
    ));
```

- [ ] **Step 2: Create down migration** `db/migrations/000033_extend_audit_operations.down.sql`

```sql
-- Restore original Phase 1 CHECK constraints
ALTER TABLE audit_trail DROP CONSTRAINT IF EXISTS audit_trail_operation_check;
ALTER TABLE audit_trail ADD CONSTRAINT audit_trail_operation_check
    CHECK (operation IN (
        'node.create', 'node.update', 'node.deprecate',
        'edge.create', 'edge.delete',
        'session.start', 'session.end', 'session.update'
    ));

ALTER TABLE audit_trail DROP CONSTRAINT IF EXISTS audit_trail_entity_type_check;
ALTER TABLE audit_trail ADD CONSTRAINT audit_trail_entity_type_check
    CHECK (entity_type IN ('node', 'edge', 'session'));
```

- [ ] **Step 3: Run migration and verify**

```bash
cd ennam.kg.go && go run ./cmd/kg-migrate/ up
```

- [ ] **Step 4: Commit**

```bash
git add db/migrations/000033_*
git commit -m "migration(033): extend audit_trail operations for Phase 2+3 (BA-016)"
```

---

## Task 3: Settings model + extend audit model

- [ ] **Step 1: Create `internal/models/settings.go`**

```go
package models

import "time"

// SettingCategory defines the allowed categories for system settings.
type SettingCategory string

const (
	SettingCategoryAI           SettingCategory = "ai"
	SettingCategorySync         SettingCategory = "sync"
	SettingCategoryAuth         SettingCategory = "auth"
	SettingCategoryFeatureFlags SettingCategory = "feature_flags"
	SettingCategoryGeneral      SettingCategory = "general"
)

// ValidSettingCategories contains all valid category values.
var ValidSettingCategories = []SettingCategory{
	SettingCategoryAI,
	SettingCategorySync,
	SettingCategoryAuth,
	SettingCategoryFeatureFlags,
	SettingCategoryGeneral,
}

// IsValid checks whether the category is recognized.
func (c SettingCategory) IsValid() bool {
	for _, v := range ValidSettingCategories {
		if c == v {
			return true
		}
	}
	return false
}

// SystemSetting represents a single platform configuration entry
// stored in the system_settings table.
type SystemSetting struct {
	// Key is the unique identifier for this setting (e.g. "ai.max_tokens_per_request").
	Key string `json:"key" db:"key"`

	// Value is the JSONB setting value (can be string, number, boolean, object).
	Value json.RawMessage `json:"value" db:"value"`

	// Description is a human-readable explanation of the setting.
	Description *string `json:"description,omitempty" db:"description"`

	// Category groups settings for display and access control.
	Category SettingCategory `json:"category" db:"category"`

	// UpdatedBy is the UUID of the user who last changed this setting.
	UpdatedBy *string `json:"updated_by,omitempty" db:"updated_by"`

	// UpdatedAt is the timestamp of the last modification.
	UpdatedAt time.Time `json:"updated_at" db:"updated_at"`
}

// IsPublic returns true if the setting should be visible to non-admin users.
// Feature flags and general settings are public; ai, sync, auth are admin-only.
func (s *SystemSetting) IsPublic() bool {
	return s.Category == SettingCategoryFeatureFlags || s.Category == SettingCategoryGeneral
}
```

**Note:** Add `import "encoding/json"` to the import block.

- [ ] **Step 2: Extend `internal/models/audit.go`** — add new constants

Add the following constants below the existing Phase 1 operations:

```go
// Phase 2 operations
const (
	AuditOpSyncStart      AuditOperation = "sync.start"
	AuditOpSyncComplete   AuditOperation = "sync.complete"
	AuditOpSyncFail       AuditOperation = "sync.fail"
	AuditOpKGGenerate     AuditOperation = "kg.generate"
	AuditOpQuerySubmit    AuditOperation = "query.submit"
	AuditOpBenchmarkRun   AuditOperation = "benchmark.run"
)

// Phase 3 operations
const (
	AuditOpAuthLogin          AuditOperation = "auth.login"
	AuditOpAuthLoginFailed    AuditOperation = "auth.login_failed"
	AuditOpAuthPasswordChange AuditOperation = "auth.password_change"
	AuditOpAuthPasswordReset  AuditOperation = "auth.password_reset"
	AuditOpAuthLogout         AuditOperation = "auth.logout"

	AuditOpUserCreate  AuditOperation = "user.create"
	AuditOpUserDisable AuditOperation = "user.disable"
	AuditOpUserEnable  AuditOperation = "user.enable"
	AuditOpUserUnlock  AuditOperation = "user.unlock"

	AuditOpMemberAdd        AuditOperation = "member.add"
	AuditOpMemberRemove     AuditOperation = "member.remove"
	AuditOpMemberRoleChange AuditOperation = "member.role_change"

	AuditOpProjectCreate    AuditOperation = "project.create"
	AuditOpProjectArchive   AuditOperation = "project.archive"
	AuditOpProjectUnarchive AuditOperation = "project.unarchive"

	AuditOpSettingUpdate AuditOperation = "setting.update"
)
```

Update `IsValid()` to include all new operations in the switch:

```go
func (o AuditOperation) IsValid() bool {
	switch o {
	case AuditOpNodeCreate, AuditOpNodeUpdate, AuditOpNodeDeprecate,
		AuditOpEdgeCreate, AuditOpEdgeDelete,
		AuditOpSessionStart, AuditOpSessionEnd, AuditOpSessionUpdate,
		// Phase 2
		AuditOpSyncStart, AuditOpSyncComplete, AuditOpSyncFail,
		AuditOpKGGenerate, AuditOpQuerySubmit, AuditOpBenchmarkRun,
		// Phase 3
		AuditOpAuthLogin, AuditOpAuthLoginFailed, AuditOpAuthPasswordChange,
		AuditOpAuthPasswordReset, AuditOpAuthLogout,
		AuditOpUserCreate, AuditOpUserDisable, AuditOpUserEnable, AuditOpUserUnlock,
		AuditOpMemberAdd, AuditOpMemberRemove, AuditOpMemberRoleChange,
		AuditOpProjectCreate, AuditOpProjectArchive, AuditOpProjectUnarchive,
		AuditOpSettingUpdate:
		return true
	}
	return false
}
```

Add new entity types:

```go
const (
	AuditEntityDataSource   AuditEntityType = "data_source"
	AuditEntitySyncJob      AuditEntityType = "sync_job"
	AuditEntityKGGeneration AuditEntityType = "kg_generation"
	AuditEntityAIQuery      AuditEntityType = "ai_query"
	AuditEntityBenchmark    AuditEntityType = "benchmark"
	AuditEntityUser         AuditEntityType = "user"
	AuditEntityMember       AuditEntityType = "member"
	AuditEntityProject      AuditEntityType = "project"
	AuditEntityAPIKey       AuditEntityType = "api_key"
	AuditEntitySetting      AuditEntityType = "setting"
)
```

Update `AuditEntityType.IsValid()` to include all new types.

- [ ] **Step 3: Write tests for model validation**

File: `internal/models/settings_test.go` — test `SettingCategory.IsValid()` and `SystemSetting.IsPublic()`.
File: Update `internal/models/audit_test.go` — test new operation and entity type constants validate correctly.

- [ ] **Step 4: Run tests**

```bash
cd ennam.kg.go && go test ./internal/models/... -v -run TestSetting
cd ennam.kg.go && go test ./internal/models/... -v -run TestAudit
```

- [ ] **Step 5: Commit**

```bash
git add internal/models/settings.go internal/models/settings_test.go internal/models/audit.go internal/models/audit_test.go
git commit -m "models: add SystemSetting + extend AuditOperation/AuditEntityType for Phase 2+3 (BA-016)"
```

---

## Task 4: Settings store

- [ ] **Step 1: Write tests first** `internal/store/settings_test.go`

Table-driven tests covering:
- `Get(ctx, key)` — returns setting by key; returns error when not found
- `GetByCategory(ctx, category)` — returns all settings in a category; empty list for unknown category
- `GetPublic(ctx)` — returns only feature_flags + general settings
- `Set(ctx, key, value, category, description, updatedBy)` — upsert; returns updated setting
- `List(ctx)` — returns all settings
- `Delete(ctx, key)` — removes setting; error when not found

Use testcontainers-go with PostgreSQL or a mock `*sql.DB`.

- [ ] **Step 2: Implement `internal/store/settings.go`**

```go
package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"

	"github.com/ennam/ennam-kg/internal/models"
)

// SettingsStore provides CRUD operations for system settings.
type SettingsStore struct {
	db *sql.DB
}

// NewSettingsStore creates a new SettingsStore.
func NewSettingsStore(db *sql.DB) *SettingsStore {
	return &SettingsStore{db: db}
}

// Get retrieves a single setting by key.
func (s *SettingsStore) Get(ctx context.Context, key string) (*models.SystemSetting, error) {
	if key == "" {
		return nil, fmt.Errorf("key is required")
	}

	query := `
		SELECT key, value, description, category, updated_by, updated_at
		FROM system_settings
		WHERE key = $1`

	var setting models.SystemSetting
	err := s.db.QueryRowContext(ctx, query, key).Scan(
		&setting.Key,
		&setting.Value,
		&setting.Description,
		&setting.Category,
		&setting.UpdatedBy,
		&setting.UpdatedAt,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("setting %q not found", key)
		}
		return nil, fmt.Errorf("get setting: %w", err)
	}

	return &setting, nil
}

// GetByCategory retrieves all settings in a specific category.
func (s *SettingsStore) GetByCategory(ctx context.Context, category models.SettingCategory) ([]models.SystemSetting, error) {
	if !category.IsValid() {
		return nil, fmt.Errorf("invalid category: %q", category)
	}

	query := `
		SELECT key, value, description, category, updated_by, updated_at
		FROM system_settings
		WHERE category = $1
		ORDER BY key`

	rows, err := s.db.QueryContext(ctx, query, string(category))
	if err != nil {
		return nil, fmt.Errorf("get settings by category: %w", err)
	}
	defer rows.Close()

	return s.scanMany(rows)
}

// GetPublic retrieves all settings visible to non-admin users
// (feature_flags and general categories).
func (s *SettingsStore) GetPublic(ctx context.Context) ([]models.SystemSetting, error) {
	query := `
		SELECT key, value, description, category, updated_by, updated_at
		FROM system_settings
		WHERE category IN ('feature_flags', 'general')
		ORDER BY category, key`

	rows, err := s.db.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("get public settings: %w", err)
	}
	defer rows.Close()

	return s.scanMany(rows)
}

// Set creates or updates a setting. Uses INSERT ... ON CONFLICT DO UPDATE (upsert).
func (s *SettingsStore) Set(ctx context.Context, key string, value json.RawMessage, category models.SettingCategory, description *string, updatedBy *string) (*models.SystemSetting, error) {
	if key == "" {
		return nil, fmt.Errorf("key is required")
	}
	if !category.IsValid() {
		return nil, fmt.Errorf("invalid category: %q", category)
	}
	if value == nil {
		return nil, fmt.Errorf("value is required")
	}

	query := `
		INSERT INTO system_settings (key, value, description, category, updated_by, updated_at)
		VALUES ($1, $2, $3, $4, $5, NOW())
		ON CONFLICT (key) DO UPDATE SET
			value = EXCLUDED.value,
			description = COALESCE(EXCLUDED.description, system_settings.description),
			category = EXCLUDED.category,
			updated_by = EXCLUDED.updated_by,
			updated_at = NOW()
		RETURNING key, value, description, category, updated_by, updated_at`

	var setting models.SystemSetting
	err := s.db.QueryRowContext(ctx, query, key, value, description, string(category), updatedBy).Scan(
		&setting.Key,
		&setting.Value,
		&setting.Description,
		&setting.Category,
		&setting.UpdatedBy,
		&setting.UpdatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("set setting: %w", err)
	}

	return &setting, nil
}

// List retrieves all settings ordered by category and key.
func (s *SettingsStore) List(ctx context.Context) ([]models.SystemSetting, error) {
	query := `
		SELECT key, value, description, category, updated_by, updated_at
		FROM system_settings
		ORDER BY category, key`

	rows, err := s.db.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("list settings: %w", err)
	}
	defer rows.Close()

	return s.scanMany(rows)
}

// Delete removes a setting by key.
func (s *SettingsStore) Delete(ctx context.Context, key string) error {
	if key == "" {
		return fmt.Errorf("key is required")
	}

	result, err := s.db.ExecContext(ctx, `DELETE FROM system_settings WHERE key = $1`, key)
	if err != nil {
		return fmt.Errorf("delete setting: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("check rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("setting %q not found", key)
	}

	return nil
}

// scanMany reads rows into a slice of SystemSetting.
func (s *SettingsStore) scanMany(rows *sql.Rows) ([]models.SystemSetting, error) {
	var settings []models.SystemSetting
	for rows.Next() {
		var setting models.SystemSetting
		if err := rows.Scan(
			&setting.Key,
			&setting.Value,
			&setting.Description,
			&setting.Category,
			&setting.UpdatedBy,
			&setting.UpdatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan setting: %w", err)
		}
		settings = append(settings, setting)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate settings: %w", err)
	}

	if settings == nil {
		settings = []models.SystemSetting{}
	}
	return settings, nil
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/store/ -v -run TestSettings
```

- [ ] **Step 4: Commit**

```bash
git add internal/store/settings.go internal/store/settings_test.go
git commit -m "store: add SettingsStore CRUD for system_settings (BA-016)"
```

---

## Task 5: Settings service (with cache + DB-over-YAML fallback)

- [ ] **Step 1: Define repository interface and write tests** `internal/service/settings_test.go`

Tests covering:
- `Get(ctx, key)` — returns DB value when exists; falls back to YAML config value; error when neither
- `Set(ctx, key, value, category, updatedBy)` — validates key, updates DB, records audit trail, invalidates cache
- Cache: second `Get()` within 60s returns cached value without DB query
- Cache refresh: after 60s, stale cache triggers background refresh
- `GetPublic(ctx)` — returns merged public settings (DB overrides YAML defaults)

- [ ] **Step 2: Implement `internal/service/settings.go`**

```go
package service

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

// SettingsRepository defines the data access interface for system settings.
type SettingsRepository interface {
	Get(ctx context.Context, key string) (*models.SystemSetting, error)
	GetByCategory(ctx context.Context, category models.SettingCategory) ([]models.SystemSetting, error)
	GetPublic(ctx context.Context) ([]models.SystemSetting, error)
	Set(ctx context.Context, key string, value json.RawMessage, category models.SettingCategory, description *string, updatedBy *string) (*models.SystemSetting, error)
	List(ctx context.Context) ([]models.SystemSetting, error)
	Delete(ctx context.Context, key string) error
}

// AuditRecorder defines the interface for recording audit trail entries.
type AuditRecorder interface {
	RecordAudit(ctx context.Context, params store.RecordAuditParams) (*models.AuditEntry, error)
}

// SettingsService provides business logic for system settings with
// in-memory caching and DB-override-over-YAML-fallback.
type SettingsService struct {
	repo     SettingsRepository
	audit    AuditRecorder
	logger   *slog.Logger

	// Cache
	mu          sync.RWMutex
	cache       map[string]*models.SystemSetting
	cacheLoaded time.Time
	cacheTTL    time.Duration
}

// NewSettingsService creates a new SettingsService.
func NewSettingsService(repo SettingsRepository, audit AuditRecorder, logger *slog.Logger) *SettingsService {
	if logger == nil {
		logger = slog.Default()
	}
	return &SettingsService{
		repo:     repo,
		audit:    audit,
		logger:   logger,
		cache:    make(map[string]*models.SystemSetting),
		cacheTTL: 60 * time.Second,
	}
}

// Get retrieves a setting by key. Checks cache first, then DB.
// Returns the setting or an error if not found.
func (s *SettingsService) Get(ctx context.Context, key string) (*models.SystemSetting, error) {
	key = strings.TrimSpace(key)
	if key == "" {
		return nil, &ValidationError{Field: "key", Message: "key is required"}
	}

	// Check cache
	s.mu.RLock()
	if cached, ok := s.cache[key]; ok && time.Since(s.cacheLoaded) < s.cacheTTL {
		s.mu.RUnlock()
		return cached, nil
	}
	s.mu.RUnlock()

	// Cache miss or stale — query DB
	setting, err := s.repo.Get(ctx, key)
	if err != nil {
		return nil, err
	}

	// Update cache
	s.mu.Lock()
	s.cache[key] = setting
	s.mu.Unlock()

	return setting, nil
}

// Set creates or updates a setting, records an audit trail entry, and
// invalidates the cache.
func (s *SettingsService) Set(ctx context.Context, key string, value json.RawMessage, category models.SettingCategory, description *string, updatedBy *string) (*models.SystemSetting, error) {
	key = strings.TrimSpace(key)
	if key == "" {
		return nil, &ValidationError{Field: "key", Message: "key is required"}
	}
	if value == nil || len(value) == 0 {
		return nil, &ValidationError{Field: "value", Message: "value is required"}
	}
	if !category.IsValid() {
		return nil, &ValidationError{Field: "category", Message: fmt.Sprintf("invalid category: %q", category)}
	}

	// Validate JSON
	if !json.Valid(value) {
		return nil, &ValidationError{Field: "value", Message: "value must be valid JSON"}
	}

	// Get old value for audit details
	var oldValue json.RawMessage
	existing, err := s.repo.Get(ctx, key)
	if err == nil && existing != nil {
		oldValue = existing.Value
	}

	// Persist
	setting, err := s.repo.Set(ctx, key, value, category, description, updatedBy)
	if err != nil {
		return nil, fmt.Errorf("set setting: %w", err)
	}

	// Record audit trail
	if s.audit != nil {
		details, _ := json.Marshal(map[string]interface{}{
			"key":       key,
			"old_value": string(oldValue),
			"new_value": string(value),
		})

		actorName := "system"
		if updatedBy != nil {
			actorName = *updatedBy
		}

		_, auditErr := s.audit.RecordAudit(ctx, store.RecordAuditParams{
			ProjectID:  "00000000-0000-0000-0000-000000000000", // system-level
			Operation:  models.AuditOpSettingUpdate,
			EntityType: models.AuditEntitySetting,
			EntityID:   key,
			Actor:      actorName,
			Details:    details,
		})
		if auditErr != nil {
			s.logger.Warn("failed to record setting update audit", "key", key, "error", auditErr)
		}
	}

	// Invalidate cache
	s.mu.Lock()
	s.cache[key] = setting
	s.cacheLoaded = time.Time{} // force full refresh on next List/GetPublic
	s.mu.Unlock()

	s.logger.Info("setting updated", "key", key, "category", string(category))

	return setting, nil
}

// GetPublic returns all settings visible to non-admin users.
func (s *SettingsService) GetPublic(ctx context.Context) ([]models.SystemSetting, error) {
	return s.repo.GetPublic(ctx)
}

// List returns all settings (admin only).
func (s *SettingsService) List(ctx context.Context) ([]models.SystemSetting, error) {
	settings, err := s.repo.List(ctx)
	if err != nil {
		return nil, err
	}

	// Refresh cache
	s.mu.Lock()
	s.cache = make(map[string]*models.SystemSetting, len(settings))
	for i := range settings {
		s.cache[settings[i].Key] = &settings[i]
	}
	s.cacheLoaded = time.Now()
	s.mu.Unlock()

	return settings, nil
}

// RefreshCache forces a cache reload from the database.
func (s *SettingsService) RefreshCache(ctx context.Context) error {
	_, err := s.List(ctx)
	return err
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/service/ -v -run TestSettings
```

- [ ] **Step 4: Commit**

```bash
git add internal/service/settings.go internal/service/settings_test.go
git commit -m "service: add SettingsService with cache and audit trail (BA-016)"
```

---

## Task 6: Settings handler (4 endpoints)

- [ ] **Step 1: Write tests first** `internal/handler/settings_test.go`

Table-driven HTTP tests for:
- `GET /api/v1/settings` — 200 with all settings (admin); 403 for non-admin
- `GET /api/v1/settings/public` — 200 with public settings (any authenticated user)
- `GET /api/v1/settings/{key}` — 200 with single setting; 404 for unknown key; 403 for non-admin
- `PUT /api/v1/settings/{key}` — 200 on success; 400 for invalid JSON; 403 for non-admin; records audit

Each test injects `DeveloperIdentity` into context to simulate auth.

- [ ] **Step 2: Implement `internal/handler/settings.go`**

```go
package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

// SettingsHandler handles system settings REST API requests.
type SettingsHandler struct {
	svc    *service.SettingsService
	logger *slog.Logger
}

// NewSettingsHandler creates a new SettingsHandler.
func NewSettingsHandler(svc *service.SettingsService, logger *slog.Logger) *SettingsHandler {
	return &SettingsHandler{svc: svc, logger: logger}
}

// settingsUpdateRequest is the JSON body for PUT /api/v1/settings/{key}.
type settingsUpdateRequest struct {
	Value       json.RawMessage        `json:"value"`
	Category    models.SettingCategory  `json:"category"`
	Description *string                `json:"description,omitempty"`
}

// HandleListSettings handles GET /api/v1/settings — admin only.
func (h *SettingsHandler) HandleListSettings(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil || identity.Role != models.APIKeyRoleAdmin {
		errorResponse(w, http.StatusForbidden, "admin access required")
		return
	}

	settings, err := h.svc.List(ctx)
	if err != nil {
		h.logger.ErrorContext(ctx, "list settings failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to list settings")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"settings": settings,
		"total":    len(settings),
	})
}

// HandleGetPublicSettings handles GET /api/v1/settings/public — any authenticated user.
func (h *SettingsHandler) HandleGetPublicSettings(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	settings, err := h.svc.GetPublic(ctx)
	if err != nil {
		h.logger.ErrorContext(ctx, "get public settings failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to get public settings")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"settings": settings,
		"total":    len(settings),
	})
}

// HandleGetSetting handles GET /api/v1/settings/{key} — admin only.
func (h *SettingsHandler) HandleGetSetting(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil || identity.Role != models.APIKeyRoleAdmin {
		errorResponse(w, http.StatusForbidden, "admin access required")
		return
	}

	key := r.PathValue("key")
	if key == "" {
		errorResponse(w, http.StatusBadRequest, "setting key is required")
		return
	}

	setting, err := h.svc.Get(ctx, key)
	if err != nil {
		if isNotFoundError(err) {
			errorResponse(w, http.StatusNotFound, err.Error())
			return
		}
		h.logger.ErrorContext(ctx, "get setting failed", "error", err, "key", key)
		errorResponse(w, http.StatusInternalServerError, "failed to get setting")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"setting": setting,
	})
}

// HandleUpdateSetting handles PUT /api/v1/settings/{key} — admin only.
func (h *SettingsHandler) HandleUpdateSetting(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil || identity.Role != models.APIKeyRoleAdmin {
		errorResponse(w, http.StatusForbidden, "admin access required")
		return
	}

	key := r.PathValue("key")
	if key == "" {
		errorResponse(w, http.StatusBadRequest, "setting key is required")
		return
	}

	var req settingsUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	if req.Value == nil || len(req.Value) == 0 {
		errorResponse(w, http.StatusBadRequest, "value is required")
		return
	}

	if req.Category == "" {
		req.Category = models.SettingCategoryGeneral
	}

	updatedBy := &identity.KeyID

	setting, err := h.svc.Set(ctx, key, req.Value, req.Category, req.Description, updatedBy)
	if err != nil {
		if isValidationError(err) {
			errorResponse(w, http.StatusBadRequest, err.Error())
			return
		}
		h.logger.ErrorContext(ctx, "update setting failed", "error", err, "key", key)
		errorResponse(w, http.StatusInternalServerError, "failed to update setting")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"setting": setting,
	})
}

// RegisterSettingsRoutes registers settings handler routes.
func (h *SettingsHandler) RegisterSettingsRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/settings", h.HandleListSettings)
	mux.HandleFunc("GET /api/v1/settings/public", h.HandleGetPublicSettings)
	mux.HandleFunc("GET /api/v1/settings/{key}", h.HandleGetSetting)
	mux.HandleFunc("PUT /api/v1/settings/{key}", h.HandleUpdateSetting)
}

// isNotFoundError checks if the error message contains "not found".
func isNotFoundError(err error) bool {
	return err != nil && contains(err.Error(), "not found")
}

// isValidationError checks if the error is a service validation error.
func isValidationError(err error) bool {
	_, ok := err.(*service.ValidationError)
	if ok {
		return true
	}
	_, ok2 := err.(*service.ValidationErrors)
	return ok2
}

// contains is a simple substring check (avoids importing strings in handler).
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && containsImpl(s, substr))
}

func containsImpl(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
```

**Note:** The `contains` helper can be replaced with `strings.Contains` if you prefer importing `strings` — the existing handlers already do.

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/handler/ -v -run TestSettings
```

- [ ] **Step 4: Commit**

```bash
git add internal/handler/settings.go internal/handler/settings_test.go
git commit -m "handler: add SettingsHandler with 4 endpoints (BA-016)"
```

---

## Task 7: API Key handler (6 endpoints — thin wrapper over existing service)

- [ ] **Step 1: Write tests first** `internal/handler/apikey_test.go`

Table-driven HTTP tests for:
- `POST /api/v1/api-keys` — 201 with plaintext key returned once; 400 for missing fields
- `GET /api/v1/api-keys` — 200 list; admin sees all, non-admin sees own keys; excludes `web-session-*` labels
- `GET /api/v1/api-keys/{id}` — 200 detail; 404 for unknown
- `PATCH /api/v1/api-keys/{id}` — 200 with updated label; 400 for empty label
- `POST /api/v1/api-keys/{id}/revoke` — 200 on success; 409 if already revoked
- `DELETE /api/v1/api-keys/{id}` — 204 on success; 403 for non-admin

- [ ] **Step 2: Implement `internal/handler/apikey.go`**

```go
package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strings"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

// APIKeyHandler handles API key management REST endpoints.
type APIKeyHandler struct {
	svc    *service.APIKeyService
	logger *slog.Logger
}

// NewAPIKeyHandler creates a new APIKeyHandler.
func NewAPIKeyHandler(svc *service.APIKeyService, logger *slog.Logger) *APIKeyHandler {
	return &APIKeyHandler{svc: svc, logger: logger}
}

// apiKeyCreateRequest is the JSON body for POST /api/v1/api-keys.
type apiKeyCreateRequest struct {
	DeveloperName    string            `json:"developer_name"`
	Label            string            `json:"label"`
	Role             models.APIKeyRole `json:"role"`
	ProjectIDs       []string          `json:"project_ids"`
	DefaultProjectID *string           `json:"default_project_id,omitempty"`
}

// apiKeyUpdateRequest is the JSON body for PATCH /api/v1/api-keys/{id}.
type apiKeyUpdateRequest struct {
	Label string `json:"label"`
}

// HandleCreateAPIKey handles POST /api/v1/api-keys.
// Returns the plaintext key once in the response.
func (h *APIKeyHandler) HandleCreateAPIKey(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req apiKeyCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	// Non-admin users can only create keys for themselves
	if identity.Role != models.APIKeyRoleAdmin {
		req.DeveloperName = identity.DeveloperName
		// Non-admin can only create viewer or developer role keys
		if req.Role == models.APIKeyRoleAdmin {
			errorResponse(w, http.StatusForbidden, "only admins can create admin keys")
			return
		}
	}

	resp, err := h.svc.CreateKey(ctx, service.CreateKeyRequest{
		DeveloperName:    req.DeveloperName,
		Label:            req.Label,
		Role:             req.Role,
		ProjectIDs:       req.ProjectIDs,
		DefaultProjectID: req.DefaultProjectID,
	})
	if err != nil {
		if isValidationError(err) {
			errorResponse(w, http.StatusBadRequest, err.Error())
			return
		}
		h.logger.ErrorContext(ctx, "create api key failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to create api key")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"api_key":      resp.Key,
		"plaintext_key": resp.PlaintextKey,
		"message":      "Store this key securely. It will not be shown again.",
	})
}

// HandleListAPIKeys handles GET /api/v1/api-keys.
// Admin sees all keys; non-admin sees own keys only.
// Excludes keys with labels starting with "web-session-".
func (h *APIKeyHandler) HandleListAPIKeys(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var listReq service.ListKeysRequest

	if identity.Role == models.APIKeyRoleAdmin {
		// Admin can optionally filter by developer
		devName := r.URL.Query().Get("developer_name")
		listReq = service.ListKeysRequest{
			DeveloperName: devName,
			ActiveOnly:    r.URL.Query().Get("active_only") != "false",
		}
	} else {
		// Non-admin only sees own keys
		listReq = service.ListKeysRequest{
			DeveloperName: identity.DeveloperName,
			ActiveOnly:    true,
		}
	}

	resp, err := h.svc.ListKeys(ctx, listReq)
	if err != nil {
		h.logger.ErrorContext(ctx, "list api keys failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to list api keys")
		return
	}

	// Filter out web-session-* labels
	filtered := make([]*models.APIKey, 0, len(resp.Keys))
	for _, k := range resp.Keys {
		if !strings.HasPrefix(k.Label, "web-session-") {
			filtered = append(filtered, k)
		}
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"api_keys": filtered,
		"total":    len(filtered),
	})
}

// HandleGetAPIKey handles GET /api/v1/api-keys/{id}.
func (h *APIKeyHandler) HandleGetAPIKey(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "api key id is required")
		return
	}

	key, err := h.svc.GetKey(ctx, id)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			errorResponse(w, http.StatusNotFound, "api key not found")
			return
		}
		h.logger.ErrorContext(ctx, "get api key failed", "error", err, "id", id)
		errorResponse(w, http.StatusInternalServerError, "failed to get api key")
		return
	}

	// Non-admin can only see own keys
	if identity.Role != models.APIKeyRoleAdmin && key.DeveloperName != identity.DeveloperName {
		errorResponse(w, http.StatusForbidden, "access denied")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"api_key": key,
	})
}

// HandleUpdateAPIKey handles PATCH /api/v1/api-keys/{id} — update label.
func (h *APIKeyHandler) HandleUpdateAPIKey(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "api key id is required")
		return
	}

	// Verify ownership (non-admin can only update own keys)
	key, err := h.svc.GetKey(ctx, id)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			errorResponse(w, http.StatusNotFound, "api key not found")
			return
		}
		h.logger.ErrorContext(ctx, "get api key for update failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to get api key")
		return
	}
	if identity.Role != models.APIKeyRoleAdmin && key.DeveloperName != identity.DeveloperName {
		errorResponse(w, http.StatusForbidden, "access denied")
		return
	}

	var req apiKeyUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	if strings.TrimSpace(req.Label) == "" {
		errorResponse(w, http.StatusBadRequest, "label is required")
		return
	}

	// UpdateLabel is on the repository directly — call via service's repo.
	// Since APIKeyService doesn't expose UpdateLabel, we call it through GetKey + repo.
	// For now, access the store directly through the service.
	// Alternative: add UpdateLabel to APIKeyService.
	//
	// Best approach: extend APIKeyService with UpdateLabel method.
	// The worker implementing this task should add:
	//   func (s *APIKeyService) UpdateLabel(ctx, id, label) (*APIKey, error)
	// which delegates to s.repo.UpdateLabel after ownership check.

	// Placeholder call — the implementer should wire this properly.
	// For the plan, we show the handler calling a service method:
	updated, err := h.svc.UpdateLabel(ctx, id, req.Label)
	if err != nil {
		h.logger.ErrorContext(ctx, "update api key label failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to update api key")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"api_key": updated,
	})
}

// HandleRevokeAPIKey handles POST /api/v1/api-keys/{id}/revoke.
func (h *APIKeyHandler) HandleRevokeAPIKey(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "api key id is required")
		return
	}

	// Verify ownership
	key, err := h.svc.GetKey(ctx, id)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			errorResponse(w, http.StatusNotFound, "api key not found")
			return
		}
		h.logger.ErrorContext(ctx, "get api key for revoke failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to get api key")
		return
	}
	if identity.Role != models.APIKeyRoleAdmin && key.DeveloperName != identity.DeveloperName {
		errorResponse(w, http.StatusForbidden, "access denied")
		return
	}

	revoked, err := h.svc.RevokeKey(ctx, service.RevokeKeyRequest{ID: id})
	if err != nil {
		if _, ok := err.(*service.KeyAlreadyRevokedError); ok {
			errorResponse(w, http.StatusConflict, err.Error())
			return
		}
		h.logger.ErrorContext(ctx, "revoke api key failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to revoke api key")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"api_key": revoked,
		"message": "api key revoked successfully",
	})
}

// HandleDeleteAPIKey handles DELETE /api/v1/api-keys/{id} — admin only.
func (h *APIKeyHandler) HandleDeleteAPIKey(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil || identity.Role != models.APIKeyRoleAdmin {
		errorResponse(w, http.StatusForbidden, "admin access required")
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "api key id is required")
		return
	}

	// Delete needs access to the store's Delete method.
	// The implementer should add DeleteKey to APIKeyService:
	//   func (s *APIKeyService) DeleteKey(ctx, id) error
	err := h.svc.DeleteKey(ctx, id)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			errorResponse(w, http.StatusNotFound, "api key not found")
			return
		}
		h.logger.ErrorContext(ctx, "delete api key failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to delete api key")
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

// RegisterAPIKeyRoutes registers API key handler routes.
func (h *APIKeyHandler) RegisterAPIKeyRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/api-keys", h.HandleCreateAPIKey)
	mux.HandleFunc("GET /api/v1/api-keys", h.HandleListAPIKeys)
	mux.HandleFunc("GET /api/v1/api-keys/{id}", h.HandleGetAPIKey)
	mux.HandleFunc("PATCH /api/v1/api-keys/{id}", h.HandleUpdateAPIKey)
	mux.HandleFunc("POST /api/v1/api-keys/{id}/revoke", h.HandleRevokeAPIKey)
	mux.HandleFunc("DELETE /api/v1/api-keys/{id}", h.HandleDeleteAPIKey)
}
```

**IMPORTANT — service methods to add:** The handler above calls `h.svc.UpdateLabel()` and `h.svc.DeleteKey()` which do not yet exist on `APIKeyService`. The implementer must add these two methods:

```go
// In internal/service/apikey.go — add:

// UpdateLabel updates the label of an API key.
func (s *APIKeyService) UpdateLabel(ctx context.Context, id string, label string) (*models.APIKey, error) {
	id = strings.TrimSpace(id)
	label = strings.TrimSpace(label)
	if id == "" {
		return nil, &ValidationError{Field: "id", Message: "id is required"}
	}
	if label == "" {
		return nil, &ValidationError{Field: "label", Message: "label is required"}
	}
	if len(label) > 255 {
		return nil, &ValidationError{Field: "label", Message: "label must be at most 255 characters"}
	}

	return s.repo.UpdateLabel(ctx, id, label)
}

// DeleteKey permanently removes an API key.
func (s *APIKeyService) DeleteKey(ctx context.Context, id string) error {
	id = strings.TrimSpace(id)
	if id == "" {
		return &ValidationError{Field: "id", Message: "id is required"}
	}
	// Need to add Delete to APIKeyRepository interface
	return s.repo.(interface{ Delete(context.Context, string) error }).Delete(ctx, id)
}
```

Also add `Delete` and `UpdateLabel` to the `APIKeyRepository` interface:

```go
// In internal/service/apikey.go — extend APIKeyRepository:
type APIKeyRepository interface {
	// ... existing methods ...
	Delete(ctx context.Context, id string) error
	UpdateLabel(ctx context.Context, id string, label string) (*models.APIKey, error)
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/handler/ -v -run TestAPIKey
cd ennam.kg.go && go test ./internal/service/ -v -run TestAPIKey
```

- [ ] **Step 4: Commit**

```bash
git add internal/handler/apikey.go internal/handler/apikey_test.go internal/service/apikey.go
git commit -m "handler: add APIKeyHandler with 6 REST endpoints (BA-016)"
```

---

## Task 8: Activity feed (extend audit store + new handler)

- [ ] **Step 1: Add store methods — write tests first** `internal/store/audit_test.go` (extend existing)

New test cases for:
- `GetActivityFeed(ctx, filter)` — returns entries with `actor_display_name` resolved via JOIN with users; scoped by project membership; pagination
- `GetActivityStats(ctx, projectIDs)` — returns counts: nodes_created (today/7d/30d), queries_run, syncs_completed

- [ ] **Step 2: Add types and methods to `internal/store/audit.go`**

```go
// ActivityFeedFilter defines filtering for the activity feed.
type ActivityFeedFilter struct {
	// ProjectIDs scopes the feed to these projects (membership-based).
	ProjectIDs []string
	// Limit for pagination (default 50, max 200).
	Limit  int
	// Offset for pagination.
	Offset int
	// Since filters entries after this time.
	Since *time.Time
}

// ActivityFeedEntry extends AuditEntry with actor display name.
type ActivityFeedEntry struct {
	models.AuditEntry
	ActorDisplayName string `json:"actor_display_name"`
}

// ActivityStats holds aggregated activity counts for dashboard.
type ActivityStats struct {
	NodesCreated    ActivityPeriodStats `json:"nodes_created"`
	QueriesRun      ActivityPeriodStats `json:"queries_run"`
	SyncsCompleted  ActivityPeriodStats `json:"syncs_completed"`
}

// ActivityPeriodStats holds counts for different time periods.
type ActivityPeriodStats struct {
	Today      int `json:"today"`
	Last7Days  int `json:"last_7_days"`
	Last30Days int `json:"last_30_days"`
}

// GetActivityFeed retrieves membership-scoped audit entries with actor display_name
// resolved via LEFT JOIN with the users table.
func (s *AuditStore) GetActivityFeed(ctx context.Context, filter ActivityFeedFilter) ([]ActivityFeedEntry, int, error) {
	if len(filter.ProjectIDs) == 0 {
		return []ActivityFeedEntry{}, 0, nil
	}

	// Apply defaults
	if filter.Limit <= 0 {
		filter.Limit = 50
	}
	if filter.Limit > 200 {
		filter.Limit = 200
	}
	if filter.Offset < 0 {
		filter.Offset = 0
	}

	// Build WHERE clause with project IN (...)
	conditions := []string{"a.project_id = ANY($1)"}
	args := []interface{}{pq.Array(filter.ProjectIDs)}
	argIdx := 2

	if filter.Since != nil {
		conditions = append(conditions, fmt.Sprintf("a.performed_at >= $%d", argIdx))
		args = append(args, *filter.Since)
		argIdx++
	}

	whereClause := strings.Join(conditions, " AND ")

	// Count query
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM audit_trail a WHERE %s", whereClause)
	var totalCount int
	if err := s.db.QueryRowContext(ctx, countQuery, args...).Scan(&totalCount); err != nil {
		return nil, 0, fmt.Errorf("count activity feed: %w", err)
	}

	// Main query with LEFT JOIN for display_name
	args = append(args, filter.Limit, filter.Offset)
	query := fmt.Sprintf(`
		SELECT a.id, a.project_id, a.operation, a.entity_type, a.entity_id, a.actor,
		       a.api_key_id, a.session_id, a.version, a.change_reason, a.details, a.performed_at,
		       COALESCE(u.display_name, a.actor) AS actor_display_name
		FROM audit_trail a
		LEFT JOIN users u ON u.email = a.actor OR u.id::text = a.actor
		WHERE %s
		ORDER BY a.performed_at DESC
		LIMIT $%d OFFSET $%d`,
		whereClause, argIdx, argIdx+1)

	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, 0, fmt.Errorf("get activity feed: %w", err)
	}
	defer rows.Close()

	entries := make([]ActivityFeedEntry, 0)
	for rows.Next() {
		var entry ActivityFeedEntry
		if err := rows.Scan(
			&entry.ID, &entry.ProjectID, &entry.Operation, &entry.EntityType,
			&entry.EntityID, &entry.Actor, &entry.APIKeyID, &entry.SessionID,
			&entry.Version, &entry.ChangeReason, &entry.Details, &entry.PerformedAt,
			&entry.ActorDisplayName,
		); err != nil {
			return nil, 0, fmt.Errorf("scan activity feed entry: %w", err)
		}
		entries = append(entries, entry)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, fmt.Errorf("iterate activity feed: %w", err)
	}

	return entries, totalCount, nil
}

// GetActivityStats returns aggregated activity counts for the given projects
// across three time windows: today, last 7 days, last 30 days.
func (s *AuditStore) GetActivityStats(ctx context.Context, projectIDs []string) (*ActivityStats, error) {
	if len(projectIDs) == 0 {
		return &ActivityStats{}, nil
	}

	query := `
		SELECT
			COUNT(*) FILTER (WHERE operation = 'node.create' AND performed_at >= CURRENT_DATE),
			COUNT(*) FILTER (WHERE operation = 'node.create' AND performed_at >= NOW() - INTERVAL '7 days'),
			COUNT(*) FILTER (WHERE operation = 'node.create' AND performed_at >= NOW() - INTERVAL '30 days'),
			COUNT(*) FILTER (WHERE operation = 'query.submit' AND performed_at >= CURRENT_DATE),
			COUNT(*) FILTER (WHERE operation = 'query.submit' AND performed_at >= NOW() - INTERVAL '7 days'),
			COUNT(*) FILTER (WHERE operation = 'query.submit' AND performed_at >= NOW() - INTERVAL '30 days'),
			COUNT(*) FILTER (WHERE operation = 'sync.complete' AND performed_at >= CURRENT_DATE),
			COUNT(*) FILTER (WHERE operation = 'sync.complete' AND performed_at >= NOW() - INTERVAL '7 days'),
			COUNT(*) FILTER (WHERE operation = 'sync.complete' AND performed_at >= NOW() - INTERVAL '30 days')
		FROM audit_trail
		WHERE project_id = ANY($1)`

	var stats ActivityStats
	err := s.db.QueryRowContext(ctx, query, pq.Array(projectIDs)).Scan(
		&stats.NodesCreated.Today, &stats.NodesCreated.Last7Days, &stats.NodesCreated.Last30Days,
		&stats.QueriesRun.Today, &stats.QueriesRun.Last7Days, &stats.QueriesRun.Last30Days,
		&stats.SyncsCompleted.Today, &stats.SyncsCompleted.Last7Days, &stats.SyncsCompleted.Last30Days,
	)
	if err != nil {
		return nil, fmt.Errorf("get activity stats: %w", err)
	}

	return &stats, nil
}
```

**Note:** Add `"github.com/lib/pq"` to the import block in audit.go if not already present.

- [ ] **Step 3: Implement `internal/handler/activity.go`**

```go
package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/store"
)

// ActivityHandler handles activity feed REST API requests.
type ActivityHandler struct {
	auditStore *store.AuditStore
	logger     *slog.Logger
}

// NewActivityHandler creates a new ActivityHandler.
func NewActivityHandler(auditStore *store.AuditStore, logger *slog.Logger) *ActivityHandler {
	return &ActivityHandler{auditStore: auditStore, logger: logger}
}

// HandleGetActivityFeed handles GET /api/v1/activity/feed.
// Returns membership-scoped activity entries with actor display_name resolution.
//
// Query parameters:
//   limit  - max results (default 50, max 200)
//   offset - pagination offset
//   since  - ISO 8601 timestamp filter
func (h *ActivityHandler) HandleGetActivityFeed(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	filter := store.ActivityFeedFilter{
		ProjectIDs: identity.ProjectIDs,
	}

	// Admin with no project scope sees all projects — use empty filter to get all
	if identity.Role == "admin" && len(identity.ProjectIDs) == 0 {
		// For admin, we need to pass a flag or query all projects.
		// Simplest approach: pass nil/empty to indicate "all projects".
		// The store method handles this by removing the project filter.
		filter.ProjectIDs = nil // signal: no project filter
	}

	// Parse pagination
	if limitStr := r.URL.Query().Get("limit"); limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil {
			filter.Limit = v
		}
	}
	if offsetStr := r.URL.Query().Get("offset"); offsetStr != "" {
		if v, err := strconv.Atoi(offsetStr); err == nil {
			filter.Offset = v
		}
	}
	if sinceStr := r.URL.Query().Get("since"); sinceStr != "" {
		t, err := time.Parse(time.RFC3339, sinceStr)
		if err != nil {
			errorResponse(w, http.StatusBadRequest, "invalid since: must be RFC 3339 format")
			return
		}
		filter.Since = &t
	}

	entries, totalCount, err := h.auditStore.GetActivityFeed(ctx, filter)
	if err != nil {
		h.logger.ErrorContext(ctx, "get activity feed failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to get activity feed")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"entries":     entries,
		"total_count": totalCount,
		"limit":       filter.Limit,
		"offset":      filter.Offset,
	})
}

// HandleGetActivityStats handles GET /api/v1/activity/stats.
// Returns aggregated activity statistics (today, 7d, 30d).
func (h *ActivityHandler) HandleGetActivityStats(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	identity := middleware.GetDeveloperIdentity(ctx)
	if identity == nil {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}

	projectIDs := identity.ProjectIDs
	if identity.Role == "admin" && len(identity.ProjectIDs) == 0 {
		projectIDs = nil // all projects
	}

	stats, err := h.auditStore.GetActivityStats(ctx, projectIDs)
	if err != nil {
		h.logger.ErrorContext(ctx, "get activity stats failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to get activity stats")
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"stats": stats,
	})
}

// RegisterActivityRoutes registers activity handler routes.
func (h *ActivityHandler) RegisterActivityRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/activity/feed", h.HandleGetActivityFeed)
	mux.HandleFunc("GET /api/v1/activity/stats", h.HandleGetActivityStats)
}
```

- [ ] **Step 4: Write handler tests** `internal/handler/activity_test.go`

Table-driven tests:
- `GET /api/v1/activity/feed` — 200 with entries; scoped by project membership; pagination works
- `GET /api/v1/activity/stats` — 200 with stats object containing today/7d/30d counts

- [ ] **Step 5: Run all tests**

```bash
cd ennam.kg.go && go test ./internal/store/ -v -run TestActivity
cd ennam.kg.go && go test ./internal/handler/ -v -run TestActivity
```

- [ ] **Step 6: Commit**

```bash
git add internal/store/audit.go internal/store/audit_test.go internal/handler/activity.go internal/handler/activity_test.go
git commit -m "handler+store: add activity feed and stats endpoints (BA-016)"
```

---

## Task 9: Wire into composition root

- [ ] **Step 1: Update `cmd/kg-server/main.go`** — add to `buildRouter()`

Add after the existing admin dashboard handler registration:

```go
// Register audit handler (existing, already present if wired).
auditStore := store.NewAuditStore(db)
auditHandler := handler.NewAuditHandler(auditStore, logger)
auditHandler.RegisterAuditRoutes(apiMux)

// Register API key handler (BA-016).
apiKeyStore := store.NewAPIKeyStore(db)
apiKeySvc := service.NewAPIKeyService(apiKeyStore, logger)
apiKeyHandler := handler.NewAPIKeyHandler(apiKeySvc, logger)
apiKeyHandler.RegisterAPIKeyRoutes(apiMux)

// Register settings handler (BA-016).
settingsStore := store.NewSettingsStore(db)
settingsSvc := service.NewSettingsService(settingsStore, auditStore, logger)
settingsHandler := handler.NewSettingsHandler(settingsSvc, logger)
settingsHandler.RegisterSettingsRoutes(apiMux)

// Register activity handler (BA-016).
activityHandler := handler.NewActivityHandler(auditStore, logger)
activityHandler.RegisterActivityRoutes(apiMux)

logger.Info("platform administration endpoints enabled (BA-016)")
```

Add the new routes to the `logger.Info("registered handlers", ...)` route list:

```go
// Platform admin routes (BA-016):
"POST /api/v1/api-keys",
"GET /api/v1/api-keys",
"GET /api/v1/api-keys/{id}",
"PATCH /api/v1/api-keys/{id}",
"POST /api/v1/api-keys/{id}/revoke",
"DELETE /api/v1/api-keys/{id}",
"GET /api/v1/settings",
"GET /api/v1/settings/public",
"GET /api/v1/settings/{key}",
"PUT /api/v1/settings/{key}",
"GET /api/v1/activity/feed",
"GET /api/v1/activity/stats",
```

- [ ] **Step 2: Verify compilation**

```bash
cd ennam.kg.go && go build ./...
```

- [ ] **Step 3: Run full test suite**

```bash
cd ennam.kg.go && make test
```

- [ ] **Step 4: Commit**

```bash
git add cmd/kg-server/main.go
git commit -m "wiring: register BA-016 platform admin handlers in composition root"
```

---

## Summary

| Task | Files | Endpoints | Tests |
|------|-------|-----------|-------|
| 1. Migration 032 | 2 migration files | — | manual verify |
| 2. Migration 033 | 2 migration files | — | manual verify |
| 3. Models | settings.go, audit.go | — | settings_test.go, audit_test.go |
| 4. Settings store | store/settings.go | — | store/settings_test.go |
| 5. Settings service | service/settings.go | — | service/settings_test.go |
| 6. Settings handler | handler/settings.go | 4 endpoints | handler/settings_test.go |
| 7. API key handler | handler/apikey.go + service extension | 6 endpoints | handler/apikey_test.go |
| 8. Activity feed | store/audit.go + handler/activity.go | 2 endpoints | store/audit_test.go + handler/activity_test.go |
| 9. Composition root | cmd/kg-server/main.go | — | go build + make test |

**Total: 12 new REST endpoints, 2 migrations, 4 new files, 3 modified files**

### Endpoint Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/v1/api-keys | any | Create API key (plaintext returned once) |
| GET | /api/v1/api-keys | any | List own keys (admin: all); excludes web-session-* |
| GET | /api/v1/api-keys/{id} | any | Get key detail |
| PATCH | /api/v1/api-keys/{id} | any | Update label |
| POST | /api/v1/api-keys/{id}/revoke | any | Revoke key |
| DELETE | /api/v1/api-keys/{id} | admin | Permanent delete |
| GET | /api/v1/settings | admin | List all settings |
| GET | /api/v1/settings/public | any | Public settings + feature flags |
| GET | /api/v1/settings/{key} | admin | Single setting |
| PUT | /api/v1/settings/{key} | admin | Update setting (records audit) |
| GET | /api/v1/activity/feed | any | Membership-scoped feed with actor display_name |
| GET | /api/v1/activity/stats | any | Aggregated stats (today/7d/30d) |

### Dependency Graph

```
Task 1 (migration 032) ──┐
Task 2 (migration 033) ──┼── Task 3 (models) ── Task 4 (settings store) ── Task 5 (settings service) ── Task 6 (settings handler) ──┐
                          │                                                                                                           ├── Task 9 (wiring)
                          └── Task 3 (models) ── Task 8 (activity feed) ─────────────────────────────────────────────────────────────┤
                                                                                                                                      │
                              Task 7 (API key handler) ──────────────────────────────────────────────────────────────────────────────┘
```

**Parallelizable:** Tasks 1+2 can run in parallel. After Task 3 completes, Tasks 4+7+8 can run in parallel. Task 5 depends on 4. Task 6 depends on 5. Task 9 depends on all others.
