# BA-007 Data Source Connection — Go API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement external PostgreSQL data source registration, connection testing, schema extraction, and incremental sync in the Go API server.

**Architecture:** Follows Phase 1's 3-layer pattern (Handler → Service → Store). New `internal/crypto/` package for AES-256-GCM credential encryption. External DB connections managed via separate `*sql.DB` pools created on-demand (not the app's own DB). Schema extraction reads `information_schema` and `pg_catalog` from the source DB.

**Tech Stack:** Go std lib, `database/sql`, `lib/pq`, AES-256-GCM (`crypto/aes`, `crypto/cipher`), golang-migrate

**BA Reference:** `ennam.kg.requirements/documents/phase2/BA-007-data-source-connection.md`

---

## File Structure

### New Files

```
internal/crypto/
├── aes.go                          # AES-256-GCM encrypt/decrypt functions
└── aes_test.go                     # Round-trip, wrong key, tampered data tests

internal/models/
├── datasource.go                   # DataSource, SourceSchema, SourceTable, SourceColumn, SourceForeignKey, SourceIndex, SyncJob models

internal/store/
├── datasource.go                   # DataSourceStore: CRUD + soft delete
├── datasource_test.go
├── schema_metadata.go              # SchemaMetadataStore: schemas, tables, columns, FKs, indexes
├── schema_metadata_test.go
├── sync_job.go                     # SyncJobStore: job tracking
└── sync_job_test.go

internal/service/
├── datasource.go                   # DataSourceService: registration, connection test, encryption
├── datasource_test.go
├── schema_extractor.go             # SchemaExtractorService: reads information_schema from source DB
├── schema_extractor_test.go
├── schema_sync.go                  # SchemaSyncService: incremental diff + update
└── schema_sync_test.go

internal/handler/
├── datasource.go                   # DataSourceHandler: REST endpoints
├── datasource_test.go
├── schema_metadata.go              # SchemaMetadataHandler: browse metadata
└── schema_metadata_test.go

db/migrations/
├── 000016_create_data_sources.up.sql
├── 000016_create_data_sources.down.sql
├── 000017_create_schema_metadata.up.sql
├── 000017_create_schema_metadata.down.sql
├── 000018_create_schema_fk_indexes.up.sql
├── 000018_create_schema_fk_indexes.down.sql
├── 000019_create_sync_jobs.up.sql
└── 000019_create_sync_jobs.down.sql
```

### Modified Files

```
cmd/kg-server/main.go              # Wire new handlers into buildRouter()
config/config.yaml                  # Add data_sources config section (if needed)
```

---

## Task 1: AES-256-GCM Encryption Package

**Files:**
- Create: `internal/crypto/aes.go`
- Test: `internal/crypto/aes_test.go`

- [ ] **Step 1: Write failing tests for encrypt/decrypt**

```go
// internal/crypto/aes_test.go
package crypto_test

import (
	"crypto/rand"
	"encoding/base64"
	"testing"

	"github.com/ennam/ennam-kg/internal/crypto"
)

func generateTestKey(t *testing.T) []byte {
	t.Helper()
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		t.Fatal(err)
	}
	return key
}

func TestEncryptDecrypt_RoundTrip(t *testing.T) {
	key := generateTestKey(t)
	plaintext := "postgresql://user:pass@host:5432/db?sslmode=require"

	ciphertext, err := crypto.Encrypt([]byte(plaintext), key)
	if err != nil {
		t.Fatalf("encrypt: %v", err)
	}

	if string(ciphertext) == plaintext {
		t.Fatal("ciphertext should differ from plaintext")
	}

	decrypted, err := crypto.Decrypt(ciphertext, key)
	if err != nil {
		t.Fatalf("decrypt: %v", err)
	}

	if string(decrypted) != plaintext {
		t.Fatalf("got %q, want %q", decrypted, plaintext)
	}
}

func TestDecrypt_WrongKey(t *testing.T) {
	key1 := generateTestKey(t)
	key2 := generateTestKey(t)

	ciphertext, err := crypto.Encrypt([]byte("secret"), key1)
	if err != nil {
		t.Fatal(err)
	}

	_, err = crypto.Decrypt(ciphertext, key2)
	if err == nil {
		t.Fatal("expected error decrypting with wrong key")
	}
}

func TestEncrypt_InvalidKeyLength(t *testing.T) {
	_, err := crypto.Encrypt([]byte("data"), []byte("short"))
	if err == nil {
		t.Fatal("expected error for short key")
	}
}

func TestDecrypt_TamperedCiphertext(t *testing.T) {
	key := generateTestKey(t)
	ciphertext, _ := crypto.Encrypt([]byte("secret"), key)

	// Flip a byte in the middle
	ciphertext[len(ciphertext)/2] ^= 0xff

	_, err := crypto.Decrypt(ciphertext, key)
	if err == nil {
		t.Fatal("expected error for tampered ciphertext")
	}
}

func TestKeyFromBase64(t *testing.T) {
	raw := generateTestKey(t)
	encoded := base64.StdEncoding.EncodeToString(raw)

	key, err := crypto.KeyFromBase64(encoded)
	if err != nil {
		t.Fatal(err)
	}
	if len(key) != 32 {
		t.Fatalf("key length: got %d, want 32", len(key))
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/crypto/... -v`
Expected: FAIL — package does not exist

- [ ] **Step 3: Implement AES-256-GCM**

```go
// internal/crypto/aes.go
package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"io"
)

// Encrypt encrypts plaintext using AES-256-GCM.
// Key must be exactly 32 bytes. Returns nonce || ciphertext (with GCM tag appended).
func Encrypt(plaintext, key []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("crypto: new cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("crypto: new gcm: %w", err)
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, fmt.Errorf("crypto: nonce: %w", err)
	}

	return gcm.Seal(nonce, nonce, plaintext, nil), nil
}

// Decrypt decrypts ciphertext produced by Encrypt.
// Key must be the same 32-byte key used for encryption.
func Decrypt(ciphertext, key []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("crypto: new cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("crypto: new gcm: %w", err)
	}

	nonceSize := gcm.NonceSize()
	if len(ciphertext) < nonceSize {
		return nil, fmt.Errorf("crypto: ciphertext too short")
	}

	nonce, ciphertextBody := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ciphertextBody, nil)
	if err != nil {
		return nil, fmt.Errorf("crypto: decrypt: %w", err)
	}

	return plaintext, nil
}

// KeyFromBase64 decodes a base64-encoded 32-byte AES key.
func KeyFromBase64(encoded string) ([]byte, error) {
	key, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return nil, fmt.Errorf("crypto: decode key: %w", err)
	}
	if len(key) != 32 {
		return nil, fmt.Errorf("crypto: key must be 32 bytes, got %d", len(key))
	}
	return key, nil
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/crypto/... -v -race`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/crypto/aes.go internal/crypto/aes_test.go
git commit -m "feat(crypto): add AES-256-GCM encryption for credential storage (BA-007/BA-009)"
```

---

## Task 2: Database Migrations (016-019)

**Files:**
- Create: `db/migrations/000016_create_data_sources.up.sql`
- Create: `db/migrations/000016_create_data_sources.down.sql`
- Create: `db/migrations/000017_create_schema_metadata.up.sql`
- Create: `db/migrations/000017_create_schema_metadata.down.sql`
- Create: `db/migrations/000018_create_schema_fk_indexes.up.sql`
- Create: `db/migrations/000018_create_schema_fk_indexes.down.sql`
- Create: `db/migrations/000019_create_sync_jobs.up.sql`
- Create: `db/migrations/000019_create_sync_jobs.down.sql`

- [ ] **Step 1: Write migration 016 — data_sources table**

```sql
-- 000016_create_data_sources.up.sql
CREATE TABLE data_sources (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    db_type         VARCHAR(50) NOT NULL DEFAULT 'postgresql',
    host            VARCHAR(255) NOT NULL,
    port            INTEGER NOT NULL DEFAULT 5432,
    database_name   VARCHAR(255) NOT NULL,
    connection_string_encrypted BYTEA NOT NULL,
    ssl_mode        VARCHAR(50) NOT NULL DEFAULT 'require',
    ssl_certificate TEXT,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    last_tested_at  TIMESTAMPTZ,
    last_test_status VARCHAR(50),
    created_by      VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,

    CONSTRAINT data_sources_db_type_check CHECK (db_type IN ('postgresql')),
    CONSTRAINT data_sources_status_check CHECK (status IN ('pending', 'connected', 'error', 'disabled')),
    CONSTRAINT data_sources_ssl_mode_check CHECK (ssl_mode IN ('require', 'verify-ca', 'verify-full')),
    CONSTRAINT data_sources_name_unique UNIQUE (project_id, name) WHERE deleted_at IS NULL
);

CREATE INDEX idx_data_sources_project_id ON data_sources(project_id);
CREATE INDEX idx_data_sources_status ON data_sources(status) WHERE deleted_at IS NULL;
```

```sql
-- 000016_create_data_sources.down.sql
DROP TABLE IF EXISTS data_sources;
```

- [ ] **Step 2: Write migration 017 — schema metadata tables**

```sql
-- 000017_create_schema_metadata.up.sql
CREATE TABLE source_schemas (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    data_source_id  UUID NOT NULL REFERENCES data_sources(id),
    schema_name     VARCHAR(255) NOT NULL,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT source_schemas_unique UNIQUE (data_source_id, schema_name)
);

CREATE TABLE source_tables (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_schema_id    UUID NOT NULL REFERENCES source_schemas(id) ON DELETE CASCADE,
    table_name          VARCHAR(255) NOT NULL,
    table_type          VARCHAR(50) NOT NULL DEFAULT 'BASE TABLE',
    row_count_estimate  BIGINT DEFAULT 0,
    description         TEXT,
    user_description    TEXT,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT source_tables_unique UNIQUE (source_schema_id, table_name)
);

CREATE TABLE source_columns (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_table_id     UUID NOT NULL REFERENCES source_tables(id) ON DELETE CASCADE,
    column_name         VARCHAR(255) NOT NULL,
    data_type           VARCHAR(255) NOT NULL,
    is_nullable         BOOLEAN NOT NULL DEFAULT true,
    is_primary_key      BOOLEAN NOT NULL DEFAULT false,
    column_default      TEXT,
    ordinal_position    INTEGER NOT NULL,
    character_maximum_length INTEGER,
    numeric_precision   INTEGER,
    description         TEXT,
    user_description    TEXT,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT source_columns_unique UNIQUE (source_table_id, column_name)
);

CREATE INDEX idx_source_tables_schema_id ON source_tables(source_schema_id);
CREATE INDEX idx_source_columns_table_id ON source_columns(source_table_id);
```

```sql
-- 000017_create_schema_metadata.down.sql
DROP TABLE IF EXISTS source_columns;
DROP TABLE IF EXISTS source_tables;
DROP TABLE IF EXISTS source_schemas;
```

- [ ] **Step 3: Write migration 018 — foreign keys and indexes**

```sql
-- 000018_create_schema_fk_indexes.up.sql
CREATE TABLE source_foreign_keys (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_table_id     UUID NOT NULL REFERENCES source_tables(id) ON DELETE CASCADE,
    constraint_name     VARCHAR(255) NOT NULL,
    column_name         VARCHAR(255) NOT NULL,
    referenced_schema   VARCHAR(255) NOT NULL DEFAULT 'public',
    referenced_table    VARCHAR(255) NOT NULL,
    referenced_column   VARCHAR(255) NOT NULL,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT source_fk_unique UNIQUE (source_table_id, constraint_name, column_name)
);

CREATE TABLE source_indexes (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_table_id     UUID NOT NULL REFERENCES source_tables(id) ON DELETE CASCADE,
    index_name          VARCHAR(255) NOT NULL,
    is_unique           BOOLEAN NOT NULL DEFAULT false,
    columns             JSONB NOT NULL DEFAULT '[]',
    index_type          VARCHAR(50) NOT NULL DEFAULT 'btree',
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT source_indexes_unique UNIQUE (source_table_id, index_name)
);

CREATE INDEX idx_source_fk_table_id ON source_foreign_keys(source_table_id);
CREATE INDEX idx_source_indexes_table_id ON source_indexes(source_table_id);
```

```sql
-- 000018_create_schema_fk_indexes.down.sql
DROP TABLE IF EXISTS source_indexes;
DROP TABLE IF EXISTS source_foreign_keys;
```

- [ ] **Step 4: Write migration 019 — sync_jobs table**

```sql
-- 000019_create_sync_jobs.up.sql
CREATE TABLE sync_jobs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    data_source_id  UUID NOT NULL REFERENCES data_sources(id),
    job_type        VARCHAR(50) NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    progress_pct    INTEGER DEFAULT 0,
    tables_total    INTEGER DEFAULT 0,
    tables_processed INTEGER DEFAULT 0,
    error_message   TEXT,
    metadata_json   JSONB,
    created_by      VARCHAR(255) NOT NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT sync_jobs_type_check CHECK (job_type IN ('schema_extraction', 'schema_sync', 'kg_generation')),
    CONSTRAINT sync_jobs_status_check CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX idx_sync_jobs_data_source ON sync_jobs(data_source_id);
CREATE INDEX idx_sync_jobs_status ON sync_jobs(status) WHERE status IN ('pending', 'running');
```

```sql
-- 000019_create_sync_jobs.down.sql
DROP TABLE IF EXISTS sync_jobs;
```

- [ ] **Step 5: Run migrations**

Run: `cd ennam.kg.go && make db-migrate`
Expected: Migrations 016-019 applied successfully

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add db/migrations/000016_* db/migrations/000017_* db/migrations/000018_* db/migrations/000019_*
git commit -m "feat(db): add data_sources, schema metadata, sync_jobs tables (BA-007)"
```

---

## Task 3: Domain Models

**Files:**
- Create: `internal/models/datasource.go`

- [ ] **Step 1: Define all BA-007 models**

```go
// internal/models/datasource.go
package models

import (
	"encoding/json"
	"time"
)

// DataSource represents an external PostgreSQL database registered for KG extraction.
type DataSource struct {
	ID                       string     `json:"id" db:"id"`
	ProjectID                string     `json:"project_id" db:"project_id"`
	Name                     string     `json:"name" db:"name"`
	Description              *string    `json:"description,omitempty" db:"description"`
	DBType                   string     `json:"db_type" db:"db_type"`
	Host                     string     `json:"host" db:"host"`
	Port                     int        `json:"port" db:"port"`
	DatabaseName             string     `json:"database_name" db:"database_name"`
	ConnectionStringEncrypted []byte    `json:"-" db:"connection_string_encrypted"`
	SSLMode                  string     `json:"ssl_mode" db:"ssl_mode"`
	SSLCertificate           *string    `json:"-" db:"ssl_certificate"`
	Status                   string     `json:"status" db:"status"`
	LastTestedAt             *time.Time `json:"last_tested_at,omitempty" db:"last_tested_at"`
	LastTestStatus           *string    `json:"last_test_status,omitempty" db:"last_test_status"`
	CreatedBy                string     `json:"created_by" db:"created_by"`
	CreatedAt                time.Time  `json:"created_at" db:"created_at"`
	UpdatedAt                time.Time  `json:"updated_at" db:"updated_at"`
	DeletedAt                *time.Time `json:"-" db:"deleted_at"`
}

// SourceSchema represents a schema within a data source.
type SourceSchema struct {
	ID           string    `json:"id" db:"id"`
	DataSourceID string    `json:"data_source_id" db:"data_source_id"`
	SchemaName   string    `json:"schema_name" db:"schema_name"`
	ExtractedAt  time.Time `json:"extracted_at" db:"extracted_at"`
}

// SourceTable represents a table within a source schema.
type SourceTable struct {
	ID               string    `json:"id" db:"id"`
	SourceSchemaID   string    `json:"source_schema_id" db:"source_schema_id"`
	TableName        string    `json:"table_name" db:"table_name"`
	TableType        string    `json:"table_type" db:"table_type"`
	RowCountEstimate int64     `json:"row_count_estimate" db:"row_count_estimate"`
	Description      *string   `json:"description,omitempty" db:"description"`
	UserDescription  *string   `json:"user_description,omitempty" db:"user_description"`
	ExtractedAt      time.Time `json:"extracted_at" db:"extracted_at"`
}

// SourceColumn represents a column within a source table.
type SourceColumn struct {
	ID                     string    `json:"id" db:"id"`
	SourceTableID          string    `json:"source_table_id" db:"source_table_id"`
	ColumnName             string    `json:"column_name" db:"column_name"`
	DataType               string    `json:"data_type" db:"data_type"`
	IsNullable             bool      `json:"is_nullable" db:"is_nullable"`
	IsPrimaryKey           bool      `json:"is_primary_key" db:"is_primary_key"`
	ColumnDefault          *string   `json:"column_default,omitempty" db:"column_default"`
	OrdinalPosition        int       `json:"ordinal_position" db:"ordinal_position"`
	CharacterMaximumLength *int      `json:"character_maximum_length,omitempty" db:"character_maximum_length"`
	NumericPrecision       *int      `json:"numeric_precision,omitempty" db:"numeric_precision"`
	Description            *string   `json:"description,omitempty" db:"description"`
	UserDescription        *string   `json:"user_description,omitempty" db:"user_description"`
	ExtractedAt            time.Time `json:"extracted_at" db:"extracted_at"`
}

// SourceForeignKey represents a foreign key relationship in the source database.
type SourceForeignKey struct {
	ID               string    `json:"id" db:"id"`
	SourceTableID    string    `json:"source_table_id" db:"source_table_id"`
	ConstraintName   string    `json:"constraint_name" db:"constraint_name"`
	ColumnName       string    `json:"column_name" db:"column_name"`
	ReferencedSchema string    `json:"referenced_schema" db:"referenced_schema"`
	ReferencedTable  string    `json:"referenced_table" db:"referenced_table"`
	ReferencedColumn string    `json:"referenced_column" db:"referenced_column"`
	ExtractedAt      time.Time `json:"extracted_at" db:"extracted_at"`
}

// SourceIndex represents an index on a source table.
type SourceIndex struct {
	ID          string          `json:"id" db:"id"`
	SourceTableID string        `json:"source_table_id" db:"source_table_id"`
	IndexName   string          `json:"index_name" db:"index_name"`
	IsUnique    bool            `json:"is_unique" db:"is_unique"`
	Columns     json.RawMessage `json:"columns" db:"columns"`
	IndexType   string          `json:"index_type" db:"index_type"`
	ExtractedAt time.Time       `json:"extracted_at" db:"extracted_at"`
}

// SyncJob tracks a schema extraction or sync operation.
type SyncJob struct {
	ID              string     `json:"id" db:"id"`
	DataSourceID    string     `json:"data_source_id" db:"data_source_id"`
	JobType         string     `json:"job_type" db:"job_type"`
	Status          string     `json:"status" db:"status"`
	ProgressPct     int        `json:"progress_pct" db:"progress_pct"`
	TablesTotal     int        `json:"tables_total" db:"tables_total"`
	TablesProcessed int        `json:"tables_processed" db:"tables_processed"`
	ErrorMessage    *string    `json:"error_message,omitempty" db:"error_message"`
	MetadataJSON    json.RawMessage `json:"metadata_json,omitempty" db:"metadata_json"`
	CreatedBy       string     `json:"created_by" db:"created_by"`
	StartedAt       *time.Time `json:"started_at,omitempty" db:"started_at"`
	CompletedAt     *time.Time `json:"completed_at,omitempty" db:"completed_at"`
	CreatedAt       time.Time  `json:"created_at" db:"created_at"`
}

// ConnectionTestResult holds the result of a 5-step connection test.
type ConnectionTestResult struct {
	Steps   []ConnectionTestStep `json:"steps"`
	Overall string               `json:"overall"` // "passed" or "failed"
}

// ConnectionTestStep represents one step in the 5-step connection test.
type ConnectionTestStep struct {
	Name     string `json:"name"`     // tcp, ssl, auth, information_schema, test_query
	Status   string `json:"status"`   // passed, failed, skipped
	Duration int64  `json:"duration_ms"`
	Error    string `json:"error,omitempty"`
}

// SyncJob status constants.
const (
	SyncJobStatusPending   = "pending"
	SyncJobStatusRunning   = "running"
	SyncJobStatusCompleted = "completed"
	SyncJobStatusFailed    = "failed"
	SyncJobStatusCancelled = "cancelled"
)

// DataSource status constants.
const (
	DataSourceStatusPending   = "pending"
	DataSourceStatusConnected = "connected"
	DataSourceStatusError     = "error"
	DataSourceStatusDisabled  = "disabled"
)
```

- [ ] **Step 2: Commit**

```bash
cd ennam.kg.go
git add internal/models/datasource.go
git commit -m "feat(models): add data source, schema metadata, sync job models (BA-007)"
```

---

## Task 4: DataSource Store (CRUD + Soft Delete)

**Files:**
- Create: `internal/store/datasource.go`
- Test: `internal/store/datasource_test.go`

- [ ] **Step 1: Write failing tests for DataSourceStore**

```go
// internal/store/datasource_test.go
package store_test

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

func TestDataSourceStore_Create(t *testing.T) {
	db := setupTestDB(t) // reuse existing test DB helper
	s := store.NewDataSourceStore(db)

	ds := &models.DataSource{
		ProjectID:                 testProjectID,
		Name:                     "test-source",
		DBType:                   "postgresql",
		Host:                     "localhost",
		Port:                     5432,
		DatabaseName:             "testdb",
		ConnectionStringEncrypted: []byte("encrypted-data"),
		SSLMode:                  "require",
		Status:                   models.DataSourceStatusPending,
		CreatedBy:                "test-user",
	}

	err := s.Create(context.Background(), ds)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if ds.ID == "" {
		t.Fatal("expected ID to be set")
	}
}

func TestDataSourceStore_GetByID(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewDataSourceStore(db)

	// Create first
	ds := &models.DataSource{
		ProjectID:                 testProjectID,
		Name:                     "get-test",
		DBType:                   "postgresql",
		Host:                     "localhost",
		Port:                     5432,
		DatabaseName:             "testdb",
		ConnectionStringEncrypted: []byte("encrypted"),
		SSLMode:                  "require",
		Status:                   models.DataSourceStatusPending,
		CreatedBy:                "test",
	}
	_ = s.Create(context.Background(), ds)

	// Get
	got, err := s.GetByID(context.Background(), ds.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Name != "get-test" {
		t.Fatalf("name: got %q, want %q", got.Name, "get-test")
	}
}

func TestDataSourceStore_SoftDelete(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewDataSourceStore(db)

	ds := &models.DataSource{
		ProjectID:                 testProjectID,
		Name:                     "delete-test",
		DBType:                   "postgresql",
		Host:                     "localhost",
		Port:                     5432,
		DatabaseName:             "testdb",
		ConnectionStringEncrypted: []byte("encrypted"),
		SSLMode:                  "require",
		Status:                   models.DataSourceStatusPending,
		CreatedBy:                "test",
	}
	_ = s.Create(context.Background(), ds)

	err := s.SoftDelete(context.Background(), ds.ID)
	if err != nil {
		t.Fatalf("soft delete: %v", err)
	}

	_, err = s.GetByID(context.Background(), ds.ID)
	if err == nil {
		t.Fatal("expected not found after soft delete")
	}
}

func TestDataSourceStore_ListByProject(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewDataSourceStore(db)

	// Create 2 sources
	for _, name := range []string{"source-a", "source-b"} {
		ds := &models.DataSource{
			ProjectID:                 testProjectID,
			Name:                     name,
			DBType:                   "postgresql",
			Host:                     "localhost",
			Port:                     5432,
			DatabaseName:             "testdb",
			ConnectionStringEncrypted: []byte("encrypted"),
			SSLMode:                  "require",
			Status:                   models.DataSourceStatusPending,
			CreatedBy:                "test",
		}
		_ = s.Create(context.Background(), ds)
	}

	list, err := s.ListByProject(context.Background(), testProjectID)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(list) < 2 {
		t.Fatalf("expected >= 2 sources, got %d", len(list))
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestDataSourceStore -v`
Expected: FAIL — DataSourceStore not defined

- [ ] **Step 3: Implement DataSourceStore**

```go
// internal/store/datasource.go
package store

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/ennam/ennam-kg/internal/models"
)

// DataSourceStore handles CRUD for data_sources table.
type DataSourceStore struct {
	db *sql.DB
}

func NewDataSourceStore(db *sql.DB) *DataSourceStore {
	return &DataSourceStore{db: db}
}

func (s *DataSourceStore) Create(ctx context.Context, ds *models.DataSource) error {
	return s.db.QueryRowContext(ctx,
		`INSERT INTO data_sources (project_id, name, description, db_type, host, port, database_name,
			connection_string_encrypted, ssl_mode, ssl_certificate, status, created_by)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
		 RETURNING id, created_at, updated_at`,
		ds.ProjectID, ds.Name, ds.Description, ds.DBType, ds.Host, ds.Port, ds.DatabaseName,
		ds.ConnectionStringEncrypted, ds.SSLMode, ds.SSLCertificate, ds.Status, ds.CreatedBy,
	).Scan(&ds.ID, &ds.CreatedAt, &ds.UpdatedAt)
}

func (s *DataSourceStore) GetByID(ctx context.Context, id string) (*models.DataSource, error) {
	ds := &models.DataSource{}
	err := s.db.QueryRowContext(ctx,
		`SELECT id, project_id, name, description, db_type, host, port, database_name,
			connection_string_encrypted, ssl_mode, ssl_certificate, status,
			last_tested_at, last_test_status, created_by, created_at, updated_at
		 FROM data_sources WHERE id = $1 AND deleted_at IS NULL`, id,
	).Scan(&ds.ID, &ds.ProjectID, &ds.Name, &ds.Description, &ds.DBType, &ds.Host, &ds.Port,
		&ds.DatabaseName, &ds.ConnectionStringEncrypted, &ds.SSLMode, &ds.SSLCertificate,
		&ds.Status, &ds.LastTestedAt, &ds.LastTestStatus, &ds.CreatedBy, &ds.CreatedAt, &ds.UpdatedAt)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("data source %s: %w", id, ErrNotFound)
	}
	return ds, err
}

func (s *DataSourceStore) ListByProject(ctx context.Context, projectID string) ([]*models.DataSource, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT id, project_id, name, description, db_type, host, port, database_name,
			ssl_mode, status, last_tested_at, last_test_status, created_by, created_at, updated_at
		 FROM data_sources WHERE project_id = $1 AND deleted_at IS NULL
		 ORDER BY created_at DESC`, projectID)
	if err != nil {
		return nil, fmt.Errorf("list data sources: %w", err)
	}
	defer rows.Close()

	var result []*models.DataSource
	for rows.Next() {
		ds := &models.DataSource{}
		if err := rows.Scan(&ds.ID, &ds.ProjectID, &ds.Name, &ds.Description, &ds.DBType,
			&ds.Host, &ds.Port, &ds.DatabaseName, &ds.SSLMode, &ds.Status,
			&ds.LastTestedAt, &ds.LastTestStatus, &ds.CreatedBy, &ds.CreatedAt, &ds.UpdatedAt); err != nil {
			return nil, fmt.Errorf("scan data source: %w", err)
		}
		result = append(result, ds)
	}
	return result, rows.Err()
}

func (s *DataSourceStore) Update(ctx context.Context, ds *models.DataSource) error {
	result, err := s.db.ExecContext(ctx,
		`UPDATE data_sources SET name = $2, description = $3, connection_string_encrypted = $4,
			ssl_mode = $5, ssl_certificate = $6, status = $7, updated_at = NOW()
		 WHERE id = $1 AND deleted_at IS NULL`, ds.ID, ds.Name, ds.Description,
		ds.ConnectionStringEncrypted, ds.SSLMode, ds.SSLCertificate, ds.Status)
	if err != nil {
		return fmt.Errorf("update data source: %w", err)
	}
	n, _ := result.RowsAffected()
	if n == 0 {
		return fmt.Errorf("data source %s: %w", ds.ID, ErrNotFound)
	}
	return nil
}

func (s *DataSourceStore) SoftDelete(ctx context.Context, id string) error {
	result, err := s.db.ExecContext(ctx,
		`UPDATE data_sources SET deleted_at = NOW(), status = 'disabled', updated_at = NOW()
		 WHERE id = $1 AND deleted_at IS NULL`, id)
	if err != nil {
		return fmt.Errorf("soft delete data source: %w", err)
	}
	n, _ := result.RowsAffected()
	if n == 0 {
		return fmt.Errorf("data source %s: %w", id, ErrNotFound)
	}
	return nil
}

func (s *DataSourceStore) UpdateTestResult(ctx context.Context, id, status string) error {
	_, err := s.db.ExecContext(ctx,
		`UPDATE data_sources SET last_tested_at = NOW(), last_test_status = $2,
			status = CASE WHEN $2 = 'passed' THEN 'connected' ELSE 'error' END,
			updated_at = NOW()
		 WHERE id = $1 AND deleted_at IS NULL`, id, status)
	return err
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestDataSourceStore -v -race`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/datasource.go internal/store/datasource_test.go
git commit -m "feat(store): add DataSourceStore with CRUD and soft delete (BA-007)"
```

---

## Task 5: Schema Metadata Store

**Files:**
- Create: `internal/store/schema_metadata.go`
- Test: `internal/store/schema_metadata_test.go`

- [ ] **Step 1: Write failing tests for bulk upsert operations**

Tests should cover:
- `UpsertSchema(ctx, dataSourceID, schemaName)` — insert or update
- `UpsertTable(ctx, schemaID, table)` — insert or update
- `BulkUpsertColumns(ctx, tableID, columns)` — batch insert
- `BulkUpsertForeignKeys(ctx, tableID, fks)` — batch insert
- `GetSchemaTree(ctx, dataSourceID)` — full tree: schemas → tables → columns → FKs

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestSchemaMetadata -v`

- [ ] **Step 3: Implement SchemaMetadataStore**

Key implementation notes:
- Use `ON CONFLICT ... DO UPDATE` for upsert operations
- `BulkUpsertColumns` uses a single INSERT with multiple value rows
- `GetSchemaTree` uses LEFT JOINs to build the full hierarchy
- All queries filter by `data_source_id` → `source_schema_id` → `source_table_id` chain

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestSchemaMetadata -v -race`

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/schema_metadata.go internal/store/schema_metadata_test.go
git commit -m "feat(store): add SchemaMetadataStore with bulk upsert (BA-007)"
```

---

## Task 6: SyncJob Store

**Files:**
- Create: `internal/store/sync_job.go`
- Test: `internal/store/sync_job_test.go`

- [ ] **Step 1: Write failing tests**

Tests for: `Create`, `GetByID`, `UpdateStatus`, `UpdateProgress`, `ListByDataSource`

- [ ] **Step 2: Implement SyncJobStore**

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/store/sync_job.go internal/store/sync_job_test.go
git commit -m "feat(store): add SyncJobStore for schema extraction tracking (BA-007)"
```

---

## Task 7: DataSource Service (Registration + Connection Test)

**Files:**
- Create: `internal/service/datasource.go`
- Test: `internal/service/datasource_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `RegisterDataSource` — encrypts connection string, validates uniqueness, creates record
- `TestConnection` — 5-step test (TCP, SSL, auth, information_schema, test query) with 10s per step
- `UpdateDataSource` — re-encrypts credentials if changed
- `DeleteDataSource` — soft delete + cancel running sync jobs
- Validation: `db_type` must be `postgresql`, SSL required, name unique per project

- [ ] **Step 2: Implement DataSourceService**

```go
// internal/service/datasource.go — key interfaces
type DataSourceService struct {
    store     *store.DataSourceStore
    syncStore *store.SyncJobStore
    encKey    []byte // from KG_ENCRYPTION_KEY
    logger    *slog.Logger
}

func (s *DataSourceService) Register(ctx context.Context, req RegisterRequest) (*models.DataSource, error)
func (s *DataSourceService) TestConnection(ctx context.Context, id string) (*models.ConnectionTestResult, error)
func (s *DataSourceService) Update(ctx context.Context, id string, req UpdateRequest) (*models.DataSource, error)
func (s *DataSourceService) Delete(ctx context.Context, id string) error
```

Connection test implementation:
1. **TCP**: `net.DialTimeout(host:port, 10s)` — verifies host reachable
2. **SSL**: `tls.Dial` with SSL cert if provided — verifies TLS handshake
3. **Auth**: `sql.Open` + `db.PingContext` — verifies credentials
4. **information_schema**: `SELECT COUNT(*) FROM information_schema.tables` — verifies read access
5. **Test query**: `SELECT 1` — verifies query execution

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/service/datasource.go internal/service/datasource_test.go
git commit -m "feat(service): add DataSourceService with encrypted registration and 5-step connection test (BA-007)"
```

---

## Task 8: Schema Extractor Service

**Files:**
- Create: `internal/service/schema_extractor.go`
- Test: `internal/service/schema_extractor_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `ExtractSchema` — connects to source DB, reads information_schema, persists metadata
- Filters out `pg_catalog`, `information_schema`, `pg_toast` schemas
- Uses `pg_class.reltuples` for row count estimates (not COUNT(*))
- Extracts: schemas, tables, columns (with types, nullability, PKs), FKs, indexes
- Creates a sync_job record with progress tracking

- [ ] **Step 2: Implement SchemaExtractorService**

Key SQL queries against source DB:
```sql
-- Schemas (exclude system)
SELECT schema_name FROM information_schema.schemata
WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')

-- Tables per schema
SELECT table_name, table_type FROM information_schema.tables
WHERE table_schema = $1

-- Row count estimates (fast)
SELECT reltuples::bigint FROM pg_class
WHERE relname = $1 AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = $2)

-- Columns per table
SELECT column_name, data_type, is_nullable, column_default, ordinal_position,
       character_maximum_length, numeric_precision
FROM information_schema.columns
WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position

-- Primary keys
SELECT kcu.column_name FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
WHERE tc.table_schema = $1 AND tc.table_name = $2 AND tc.constraint_type = 'PRIMARY KEY'

-- Foreign keys
SELECT tc.constraint_name, kcu.column_name,
       ccu.table_schema AS referenced_schema, ccu.table_name AS referenced_table,
       ccu.column_name AS referenced_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
WHERE tc.table_schema = $1 AND tc.table_name = $2 AND tc.constraint_type = 'FOREIGN KEY'

-- Indexes
SELECT indexname, indexdef FROM pg_indexes
WHERE schemaname = $1 AND tablename = $2
```

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/service/schema_extractor.go internal/service/schema_extractor_test.go
git commit -m "feat(service): add SchemaExtractorService reading information_schema (BA-007)"
```

---

## Task 9: Schema Sync Service (Incremental)

**Files:**
- Create: `internal/service/schema_sync.go`
- Test: `internal/service/schema_sync_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `SyncSchema` — detects added tables, dropped tables, added columns, type changes
- Generates diff report JSON
- Preserves user_description annotations during re-sync
- Dry-run mode: returns diff without persisting

- [ ] **Step 2: Implement SchemaSyncService**

Change detection categories:
- `table_added`, `table_dropped`
- `column_added`, `column_dropped`, `column_type_changed`
- `fk_added`, `fk_dropped`
- `index_added`, `index_dropped`

Algorithm:
1. Extract current schema from source DB (reuse SchemaExtractor)
2. Load existing metadata from our DB
3. Diff: compare tables, columns, FKs, indexes by name
4. If not dry-run: apply changes (upsert new, mark removed)
5. Return diff report

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/service/schema_sync.go internal/service/schema_sync_test.go
git commit -m "feat(service): add SchemaSyncService with incremental diff detection (BA-007)"
```

---

## Task 10: DataSource Handler (REST Endpoints)

**Files:**
- Create: `internal/handler/datasource.go`
- Test: `internal/handler/datasource_test.go`

- [ ] **Step 1: Write failing tests for all 10 endpoints**

```go
// Test table covering all endpoints:
// POST   /api/v1/data-sources              → 201 Created
// GET    /api/v1/data-sources              → 200 OK (list)
// GET    /api/v1/data-sources/{id}         → 200 OK (detail, credentials masked)
// PATCH  /api/v1/data-sources/{id}         → 200 OK (update)
// DELETE /api/v1/data-sources/{id}         → 204 No Content (soft delete)
// POST   /api/v1/data-sources/{id}/test-connection    → 200 OK (5-step result)
// POST   /api/v1/data-sources/{id}/extract-schema     → 202 Accepted (async job)
// POST   /api/v1/data-sources/{id}/sync-schema        → 202 Accepted (async job)
// GET    /api/v1/data-sources/{id}/sync-jobs           → 200 OK (job list)
// GET    /api/v1/data-sources/{id}/metadata            → 200 OK (schema tree)
```

Key test cases:
- Registration masks connection string in response
- Super admin role required for create/update/delete
- Duplicate name returns 409
- Non-postgresql db_type returns 400

- [ ] **Step 2: Implement DataSourceHandler**

```go
type DataSourceHandler struct {
    svc       *service.DataSourceService
    extractor *service.SchemaExtractorService
    syncer    *service.SchemaSyncService
    metaStore *store.SchemaMetadataStore
    jobStore  *store.SyncJobStore
    logger    *slog.Logger
}

func (h *DataSourceHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("POST /api/v1/data-sources", h.Create)
    mux.HandleFunc("GET /api/v1/data-sources", h.List)
    mux.HandleFunc("GET /api/v1/data-sources/{id}", h.Get)
    mux.HandleFunc("PATCH /api/v1/data-sources/{id}", h.Update)
    mux.HandleFunc("DELETE /api/v1/data-sources/{id}", h.Delete)
    mux.HandleFunc("POST /api/v1/data-sources/{id}/test-connection", h.TestConnection)
    mux.HandleFunc("POST /api/v1/data-sources/{id}/extract-schema", h.ExtractSchema)
    mux.HandleFunc("POST /api/v1/data-sources/{id}/sync-schema", h.SyncSchema)
    mux.HandleFunc("GET /api/v1/data-sources/{id}/sync-jobs", h.ListSyncJobs)
    mux.HandleFunc("GET /api/v1/data-sources/{id}/metadata", h.GetMetadata)
}
```

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/handler/datasource.go internal/handler/datasource_test.go
git commit -m "feat(handler): add DataSourceHandler with 10 REST endpoints (BA-007)"
```

---

## Task 11: Wire into Composition Root

**Files:**
- Modify: `cmd/kg-server/main.go`

- [ ] **Step 1: Add DataSource handlers to buildRouter()**

Add after the existing project handler registration:

```go
// Register data source handlers (BA-007).
encKeyB64 := os.Getenv("KG_ENCRYPTION_KEY")
if encKeyB64 != "" {
    encKey, err := crypto.KeyFromBase64(encKeyB64)
    if err != nil {
        logger.Error("invalid KG_ENCRYPTION_KEY", "error", err)
    } else {
        dsStore := store.NewDataSourceStore(db)
        metaStore := store.NewSchemaMetadataStore(db)
        jobStore := store.NewSyncJobStore(db)
        dsSvc := service.NewDataSourceService(dsStore, jobStore, encKey, logger)
        extractorSvc := service.NewSchemaExtractorService(metaStore, jobStore, encKey, logger)
        syncSvc := service.NewSchemaSyncService(metaStore, jobStore, extractorSvc, logger)
        dsHandler := handler.NewDataSourceHandler(dsSvc, extractorSvc, syncSvc, metaStore, jobStore, logger)
        dsHandler.RegisterRoutes(apiMux)
    }
} else {
    logger.Warn("KG_ENCRYPTION_KEY not set, data source endpoints disabled")
}
```

- [ ] **Step 2: Run full test suite**

Run: `cd ennam.kg.go && make test`
Expected: All tests pass including new BA-007 tests

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.go
git add cmd/kg-server/main.go
git commit -m "feat(server): wire DataSource handlers into composition root (BA-007)"
```

---

## Task 12: Integration Test — Full Registration Flow

**Files:**
- Create: `internal/handler/datasource_integration_test.go`

- [ ] **Step 1: Write end-to-end test**

Test flow:
1. POST /data-sources → register with encrypted creds → 201
2. POST /data-sources/{id}/test-connection → 5-step result → 200
3. POST /data-sources/{id}/extract-schema → job created → 202
4. GET /data-sources/{id}/sync-jobs → job status → 200
5. GET /data-sources/{id}/metadata → schema tree → 200
6. POST /data-sources/{id}/sync-schema → incremental sync → 202
7. DELETE /data-sources/{id} → soft delete → 204
8. GET /data-sources/{id} → 404

- [ ] **Step 2: Run integration test**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestDataSource_Integration -v -race`

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.go
git add internal/handler/datasource_integration_test.go
git commit -m "test: add BA-007 data source integration test covering full registration flow"
```
