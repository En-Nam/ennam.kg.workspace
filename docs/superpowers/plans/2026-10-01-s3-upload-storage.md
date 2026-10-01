# S3 Upload Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store new DAAB uploads in S3 (kg-server is the only S3 client), keep local disk as the default, and let the Python worker fetch files through the existing download endpoint.

**Architecture:** A new Go package `internal/storage` exposes `ObjectStorage` (`Put`/`Open`/`Delete`) with a `LocalStorage` and an `S3Storage`, chosen from env at startup. `FileUploadService` and the download handler use it instead of `os.*`/`http.ServeFile`. The worker downloads the upload via `KGClient.download_upload` into a temp dir before extraction.

**Tech Stack:** Go 1.25 (`aws-sdk-go-v2` s3 + manager), Python 3.12 (httpx, pytest-asyncio, `uv`), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-01-s3-upload-storage-design.md`

## Repos and branches

`ennam.kg.go/` and `ennam.kg.python/` are **separate git repos**, each currently on `task/implement_docs_sync`. Commit Go work with `git -C ennam.kg.go …`, Python work with `git -C ennam.kg.python …`, and workspace files (compose, env example, specs, plans) in the workspace repo. Commit on the current branch; do not push.

## Global Constraints

- Env var names, verbatim: `USE_S3`, `AWS_STORAGE_BUCKET_NAME`, `AWS_MAIN_FOLDER`, `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, plus the existing `KG_UPLOAD_DIR`.
- S3 bucket in use: `devshared-ap-southeast-1-public-storage`, folder `media/daab`, region `ap-southeast-1`.
- `stored_path` stays the **relative** `<project>/<upload>/<file>`; the S3 prefix is added only inside `S3Storage`. No DB schema change.
- Objects are private: never set an ACL.
- Credentials: both `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` set → static; both empty → default credential chain; exactly one set → startup error.
- Worker and indexer get no AWS variables.
- No real AWS calls in automated tests. Code comments and commit messages in English; commit trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Deviations from the spec text, decided while planning (Task 5 updates the spec): `Put` has no `size` argument (nothing needs it); `Download` sets `Content-Type` but **not** `Content-Disposition` (the old `http.ServeFile` never set it, and forcing `attachment` could break inline viewing); `USE_S3` accepts `1`/`true` (case-insensitive) as on, `""`/`0`/`false` as off, and any other value is a startup error (a typo like `yes` must not silently fall back to disk).

## Review Focus

1. A tampered/odd `stored_path` such as `../../etc/passwd` or `/abs` must be rejected by both backends, never read or written. (Task 1, Task 2)
2. `AWS_MAIN_FOLDER` given as `/media/daab/` or empty must still produce clean keys. (Task 2)
3. `USE_S3=yes` (typo) must fail startup, not silently use disk; `USE_S3=TRUE` must work. (Task 2)
4. Downloading an upload whose object is missing (the 267 pre-existing prod rows) must be 404, not 500. (Task 3)
5. An over-size upload must not leave an object behind, and a DB failure after `Put` must delete the object. (Task 3)
6. Zero-byte upload must round-trip. (Task 1)
7. Worker: the temp file must be gone even when extraction raises, and a message without `upload_id` must still use the old disk path. (Task 4)

---

### Task 1: `storage` package — interface and `LocalStorage`

**Files:**
- Create: `ennam.kg.go/internal/storage/storage.go`
- Create: `ennam.kg.go/internal/storage/local.go`
- Test: `ennam.kg.go/internal/storage/local_test.go`

**Interfaces:**
- Produces:
  - `var ErrNotFound error`
  - `type ObjectStorage interface { Put(ctx context.Context, key string, r io.Reader, contentType string) error; Open(ctx context.Context, key string) (io.ReadCloser, error); Delete(ctx context.Context, key string) error }`
  - `func NewLocalStorage(root string) *LocalStorage`

- [ ] **Step 1: Write the failing tests**

```go
// ennam.kg.go/internal/storage/local_test.go
package storage

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/iotest"
)

func readAll(t *testing.T, s ObjectStorage, key string) string {
	t.Helper()
	rc, err := s.Open(context.Background(), key)
	if err != nil {
		t.Fatalf("Open(%q): %v", key, err)
	}
	defer rc.Close()
	b, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	return string(b)
}

func TestLocalStorage_RoundTrip(t *testing.T) {
	s := NewLocalStorage(t.TempDir())
	if err := s.Put(context.Background(), "p/u/a b.txt", strings.NewReader("hello"), "text/plain"); err != nil {
		t.Fatalf("Put: %v", err)
	}
	if got := readAll(t, s, "p/u/a b.txt"); got != "hello" {
		t.Errorf("got %q, want hello", got)
	}
}

func TestLocalStorage_ZeroByteFileRoundTrips(t *testing.T) {
	s := NewLocalStorage(t.TempDir())
	if err := s.Put(context.Background(), "p/u/empty.txt", strings.NewReader(""), ""); err != nil {
		t.Fatalf("Put: %v", err)
	}
	if got := readAll(t, s, "p/u/empty.txt"); got != "" {
		t.Errorf("got %q, want empty", got)
	}
}

func TestLocalStorage_OpenMissingIsErrNotFound(t *testing.T) {
	s := NewLocalStorage(t.TempDir())
	_, err := s.Open(context.Background(), "p/u/missing.txt")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("err = %v, want ErrNotFound", err)
	}
}

func TestLocalStorage_DeleteRemovesAndMissingIsNotAnError(t *testing.T) {
	s := NewLocalStorage(t.TempDir())
	ctx := context.Background()
	_ = s.Put(ctx, "p/u/x.txt", strings.NewReader("x"), "")
	if err := s.Delete(ctx, "p/u/x.txt"); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, err := s.Open(ctx, "p/u/x.txt"); !errors.Is(err, ErrNotFound) {
		t.Errorf("after delete err = %v, want ErrNotFound", err)
	}
	if err := s.Delete(ctx, "p/u/never-existed.txt"); err != nil {
		t.Errorf("Delete of absent key = %v, want nil", err)
	}
}

func TestLocalStorage_RejectsKeysThatEscapeTheRoot(t *testing.T) {
	root := t.TempDir()
	s := NewLocalStorage(filepath.Join(root, "uploads"))
	ctx := context.Background()
	for _, key := range []string{"", "../x", "a/../../x", "/abs/path", "..", "../../etc/passwd"} {
		if err := s.Put(ctx, key, strings.NewReader("evil"), ""); err == nil {
			t.Errorf("Put(%q) succeeded, want error", key)
		}
		if _, err := s.Open(ctx, key); err == nil || errors.Is(err, ErrNotFound) {
			t.Errorf("Open(%q) err = %v, want a non-NotFound error", key, err)
		}
		if err := s.Delete(ctx, key); err == nil {
			t.Errorf("Delete(%q) succeeded, want error", key)
		}
	}
	if _, err := os.Stat(filepath.Join(root, "x")); err == nil {
		t.Error("a file was written outside the storage root")
	}
}

func TestLocalStorage_FailedPutLeavesNoPartialFile(t *testing.T) {
	s := NewLocalStorage(t.TempDir())
	r := io.MultiReader(strings.NewReader("abc"), iotest.ErrReader(errors.New("boom")))
	if err := s.Put(context.Background(), "p/u/partial.txt", r, ""); err == nil {
		t.Fatal("Put succeeded, want the reader error")
	}
	if _, err := s.Open(context.Background(), "p/u/partial.txt"); !errors.Is(err, ErrNotFound) {
		t.Errorf("partial file left behind, Open err = %v", err)
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/storage/ -run TestLocalStorage -v`
Expected: FAIL (package does not compile: `NewLocalStorage`, `ErrNotFound`, `ObjectStorage` undefined).

- [ ] **Step 3: Implement**

```go
// ennam.kg.go/internal/storage/storage.go
// Package storage abstracts where uploaded files live (local disk or S3).
package storage

import (
	"context"
	"errors"
	"io"
)

// ErrNotFound is returned by Open when the object does not exist.
var ErrNotFound = errors.New("storage: object not found")

// ObjectStorage stores uploaded files by a relative, slash-separated key
// ("<project>/<upload>/<file>"). Implementations must reject keys that are
// empty, absolute, or climb out of their root with "..".
type ObjectStorage interface {
	// Put stores r under key, replacing any existing object. A failed Put must
	// not leave a partial object behind.
	Put(ctx context.Context, key string, r io.Reader, contentType string) error
	// Open returns the object's content, or ErrNotFound.
	Open(ctx context.Context, key string) (io.ReadCloser, error)
	// Delete removes the object. Deleting an absent key is not an error.
	Delete(ctx context.Context, key string) error
}
```

```go
// ennam.kg.go/internal/storage/local.go
package storage

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// LocalStorage keeps objects as files under root (the pre-S3 behaviour).
type LocalStorage struct {
	root string
}

// NewLocalStorage returns a LocalStorage rooted at root.
func NewLocalStorage(root string) *LocalStorage {
	return &LocalStorage{root: root}
}

func (s *LocalStorage) resolve(key string) (string, error) {
	clean := filepath.Clean(filepath.FromSlash(key))
	if key == "" || filepath.IsAbs(clean) || clean == ".." ||
		strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("storage: invalid key %q", key)
	}
	return filepath.Join(s.root, clean), nil
}

func (s *LocalStorage) Put(_ context.Context, key string, r io.Reader, _ string) error {
	path, err := s.resolve(key)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create upload directory: %w", err)
	}
	dst, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return fmt.Errorf("create stored file: %w", err)
	}
	if _, err := io.Copy(dst, r); err != nil {
		_ = dst.Close()
		_ = os.Remove(path)
		return fmt.Errorf("store upload file: %w", err)
	}
	if err := dst.Close(); err != nil {
		_ = os.Remove(path)
		return fmt.Errorf("close stored file: %w", err)
	}
	return nil
}

func (s *LocalStorage) Open(_ context.Context, key string) (io.ReadCloser, error) {
	path, err := s.resolve(key)
	if err != nil {
		return nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return f, nil
}

func (s *LocalStorage) Delete(_ context.Context, key string) error {
	path, err := s.resolve(key)
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/storage/ -run TestLocalStorage -v -race`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/storage/storage.go internal/storage/local.go internal/storage/local_test.go
git -C ennam.kg.go commit -m "feat(storage): add ObjectStorage interface and local-disk implementation

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `S3Storage`, config parsing and factory

**Files:**
- Create: `ennam.kg.go/internal/storage/s3.go`
- Create: `ennam.kg.go/internal/storage/config.go`
- Modify: `ennam.kg.go/go.mod`, `ennam.kg.go/go.sum` (via `go get`)
- Test: `ennam.kg.go/internal/storage/s3_test.go`, `ennam.kg.go/internal/storage/config_test.go`

**Interfaces:**
- Consumes: `ObjectStorage`, `ErrNotFound`, `NewLocalStorage` (Task 1).
- Produces:
  - `type Config struct { UseS3 bool; Bucket, Folder, Region, AccessKeyID, SecretAccessKey, LocalRoot string }`
  - `func ConfigFromEnv(getenv func(string) string) (Config, error)`
  - `func (c Config) Backend() string` — `"s3"` or `"local"`
  - `func New(ctx context.Context, cfg Config) (ObjectStorage, error)`
  - `func newS3WithAPI(api s3API, bucket, folder string) *S3Storage` (test seam)

- [ ] **Step 1: Add the SDK modules**

Run: `cd ennam.kg.go && go get github.com/aws/aws-sdk-go-v2/service/s3 github.com/aws/aws-sdk-go-v2/feature/s3/manager && go mod tidy`
Expected: `go.mod` gains the two modules; no error.

- [ ] **Step 2: Write the failing config tests**

```go
// ennam.kg.go/internal/storage/config_test.go
package storage

import (
	"strings"
	"testing"
)

func env(m map[string]string) func(string) string {
	return func(k string) string { return m[k] }
}

func TestConfigFromEnv_DefaultsToLocal(t *testing.T) {
	cfg, err := ConfigFromEnv(env(map[string]string{}))
	if err != nil || cfg.UseS3 || cfg.LocalRoot != "./data/uploads" || cfg.Backend() != "local" {
		t.Fatalf("cfg=%+v err=%v", cfg, err)
	}
}

func TestConfigFromEnv_LocalRootFromKGUploadDir(t *testing.T) {
	cfg, _ := ConfigFromEnv(env(map[string]string{"KG_UPLOAD_DIR": "/app/data/uploads"}))
	if cfg.LocalRoot != "/app/data/uploads" {
		t.Errorf("LocalRoot = %q", cfg.LocalRoot)
	}
}

func TestConfigFromEnv_USES3Values(t *testing.T) {
	s3env := func(v string) map[string]string {
		return map[string]string{
			"USE_S3": v, "AWS_STORAGE_BUCKET_NAME": "b", "AWS_S3_REGION_NAME": "ap-southeast-1",
		}
	}
	for _, v := range []string{"1", "true", "TRUE", " true "} {
		cfg, err := ConfigFromEnv(env(s3env(v)))
		if err != nil || !cfg.UseS3 || cfg.Backend() != "s3" {
			t.Errorf("USE_S3=%q → cfg=%+v err=%v, want S3", v, cfg, err)
		}
	}
	for _, v := range []string{"", "0", "false", "FALSE"} {
		cfg, err := ConfigFromEnv(env(s3env(v)))
		if err != nil || cfg.UseS3 {
			t.Errorf("USE_S3=%q → cfg=%+v err=%v, want local", v, cfg, err)
		}
	}
	// A typo must not silently fall back to disk.
	for _, v := range []string{"yes", "on", "enabled", "2"} {
		if _, err := ConfigFromEnv(env(s3env(v))); err == nil || !strings.Contains(err.Error(), "USE_S3") {
			t.Errorf("USE_S3=%q → err=%v, want an error naming USE_S3", v, err)
		}
	}
}

func TestConfigFromEnv_S3RequiresBucketAndRegion(t *testing.T) {
	_, err := ConfigFromEnv(env(map[string]string{"USE_S3": "1", "AWS_S3_REGION_NAME": "r"}))
	if err == nil || !strings.Contains(err.Error(), "AWS_STORAGE_BUCKET_NAME") {
		t.Errorf("missing bucket err = %v", err)
	}
	_, err = ConfigFromEnv(env(map[string]string{"USE_S3": "1", "AWS_STORAGE_BUCKET_NAME": "b"}))
	if err == nil || !strings.Contains(err.Error(), "AWS_S3_REGION_NAME") {
		t.Errorf("missing region err = %v", err)
	}
}

func TestConfigFromEnv_Credentials(t *testing.T) {
	base := map[string]string{"USE_S3": "1", "AWS_STORAGE_BUCKET_NAME": "b", "AWS_S3_REGION_NAME": "r"}
	with := func(extra map[string]string) map[string]string {
		m := map[string]string{}
		for k, v := range base {
			m[k] = v
		}
		for k, v := range extra {
			m[k] = v
		}
		return m
	}
	if _, err := ConfigFromEnv(env(with(nil))); err != nil {
		t.Errorf("no credentials (IAM role) should be valid: %v", err)
	}
	if _, err := ConfigFromEnv(env(with(map[string]string{"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "s"}))); err != nil {
		t.Errorf("both credentials should be valid: %v", err)
	}
	if _, err := ConfigFromEnv(env(with(map[string]string{"AWS_ACCESS_KEY_ID": "a"}))); err == nil {
		t.Error("only the access key id set should be an error")
	}
	if _, err := ConfigFromEnv(env(with(map[string]string{"AWS_SECRET_ACCESS_KEY": "s"}))); err == nil {
		t.Error("only the secret set should be an error")
	}
}

func TestConfigFromEnv_FolderIsTrimmed(t *testing.T) {
	cfg, _ := ConfigFromEnv(env(map[string]string{
		"USE_S3": "1", "AWS_STORAGE_BUCKET_NAME": "b", "AWS_S3_REGION_NAME": "r", "AWS_MAIN_FOLDER": " /media/daab/ ",
	}))
	if cfg.Folder != "media/daab" {
		t.Errorf("Folder = %q, want media/daab", cfg.Folder)
	}
}
```

- [ ] **Step 3: Write the failing S3 tests**

```go
// ennam.kg.go/internal/storage/s3_test.go
package storage

import (
	"bytes"
	"context"
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/feature/s3/manager"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
)

type fakeS3 struct {
	objects map[string][]byte
	inputs  []*s3.PutObjectInput
	deleted []string
	getErr  error
}

func newFakeS3() *fakeS3 { return &fakeS3{objects: map[string][]byte{}} }

func (f *fakeS3) Upload(_ context.Context, in *s3.PutObjectInput, _ ...func(*manager.Uploader)) (*manager.UploadOutput, error) {
	b, err := io.ReadAll(in.Body)
	if err != nil {
		return nil, err
	}
	f.objects[*in.Key] = b
	f.inputs = append(f.inputs, in)
	return &manager.UploadOutput{}, nil
}

func (f *fakeS3) GetObject(_ context.Context, in *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	if f.getErr != nil {
		return nil, f.getErr
	}
	b, ok := f.objects[*in.Key]
	if !ok {
		return nil, &types.NoSuchKey{}
	}
	return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(b))}, nil
}

func (f *fakeS3) DeleteObject(_ context.Context, in *s3.DeleteObjectInput, _ ...func(*s3.Options)) (*s3.DeleteObjectOutput, error) {
	f.deleted = append(f.deleted, *in.Key)
	delete(f.objects, *in.Key)
	return &s3.DeleteObjectOutput{}, nil
}

func TestS3Storage_PutAppliesPrefixAndNeverSetsACL(t *testing.T) {
	f := newFakeS3()
	s := newS3WithAPI(f, "bkt", "media/daab")
	if err := s.Put(context.Background(), "p/u/f.pdf", strings.NewReader("data"), "application/pdf"); err != nil {
		t.Fatalf("Put: %v", err)
	}
	if string(f.objects["media/daab/p/u/f.pdf"]) != "data" {
		t.Fatalf("object not stored under the prefixed key: %v", f.objects)
	}
	in := f.inputs[0]
	if *in.Bucket != "bkt" {
		t.Errorf("bucket = %q", *in.Bucket)
	}
	if in.ACL != "" {
		t.Errorf("ACL = %q, objects must stay private (no ACL)", in.ACL)
	}
	if in.ContentType == nil || *in.ContentType != "application/pdf" {
		t.Errorf("content type not forwarded")
	}
}

func TestS3Storage_OpenReturnsContentAndMapsNoSuchKey(t *testing.T) {
	f := newFakeS3()
	s := newS3WithAPI(f, "bkt", "media/daab")
	_ = s.Put(context.Background(), "p/u/f.txt", strings.NewReader("hi"), "")
	rc, err := s.Open(context.Background(), "p/u/f.txt")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	b, _ := io.ReadAll(rc)
	rc.Close()
	if string(b) != "hi" {
		t.Errorf("got %q", b)
	}
	if _, err := s.Open(context.Background(), "p/u/missing.txt"); !errors.Is(err, ErrNotFound) {
		t.Errorf("missing err = %v, want ErrNotFound", err)
	}
}

func TestS3Storage_OtherErrorsAreNotMistakenForNotFound(t *testing.T) {
	f := newFakeS3()
	f.getErr = errors.New("AccessDenied")
	s := newS3WithAPI(f, "bkt", "media/daab")
	_, err := s.Open(context.Background(), "p/u/f.txt")
	if err == nil || errors.Is(err, ErrNotFound) {
		t.Errorf("err = %v, want a non-NotFound error", err)
	}
}

func TestS3Storage_DeleteUsesPrefixedKey(t *testing.T) {
	f := newFakeS3()
	s := newS3WithAPI(f, "bkt", "media/daab")
	if err := s.Delete(context.Background(), "p/u/f.txt"); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if len(f.deleted) != 1 || f.deleted[0] != "media/daab/p/u/f.txt" {
		t.Errorf("deleted = %v", f.deleted)
	}
}

func TestS3Storage_FolderNormalisation(t *testing.T) {
	cases := map[string]string{
		"media/daab":   "media/daab/p/u/f",
		"/media/daab/": "media/daab/p/u/f",
		"":             "p/u/f",
	}
	for folder, want := range cases {
		f := newFakeS3()
		s := newS3WithAPI(f, "b", folder)
		_ = s.Put(context.Background(), "p/u/f", strings.NewReader("x"), "")
		if _, ok := f.objects[want]; !ok {
			t.Errorf("folder %q → keys %v, want %q", folder, f.objects, want)
		}
	}
}

func TestS3Storage_RejectsKeysThatEscapeThePrefix(t *testing.T) {
	f := newFakeS3()
	s := newS3WithAPI(f, "b", "media/daab")
	for _, key := range []string{"", "../x", "a/../../x", "/abs", ".."} {
		if err := s.Put(context.Background(), key, strings.NewReader("x"), ""); err == nil {
			t.Errorf("Put(%q) succeeded, want error", key)
		}
		if _, err := s.Open(context.Background(), key); err == nil || errors.Is(err, ErrNotFound) {
			t.Errorf("Open(%q) err = %v, want a non-NotFound error", key, err)
		}
		if err := s.Delete(context.Background(), key); err == nil {
			t.Errorf("Delete(%q) succeeded, want error", key)
		}
	}
	if len(f.objects) != 0 || len(f.deleted) != 0 {
		t.Errorf("S3 was called for a rejected key: %v %v", f.objects, f.deleted)
	}
}

func TestNew_ReturnsLocalWhenS3IsOff(t *testing.T) {
	st, err := New(context.Background(), Config{LocalRoot: t.TempDir()})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if _, ok := st.(*LocalStorage); !ok {
		t.Errorf("got %T, want *LocalStorage", st)
	}
}
```

- [ ] **Step 4: Run to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/storage/ -v 2>&1 | tail -15`
Expected: FAIL (compile: `ConfigFromEnv`, `newS3WithAPI`, `New`, `Config` undefined).

- [ ] **Step 5: Implement config**

```go
// ennam.kg.go/internal/storage/config.go
package storage

import (
	"context"
	"fmt"
	"strings"
)

const defaultLocalRoot = "./data/uploads"

// Config selects and configures the upload storage backend.
type Config struct {
	UseS3           bool
	Bucket          string
	Folder          string // key prefix, no leading/trailing slash
	Region          string
	AccessKeyID     string // empty together with SecretAccessKey → default credential chain
	SecretAccessKey string
	LocalRoot       string
}

// Backend names the selected backend for logging.
func (c Config) Backend() string {
	if c.UseS3 {
		return "s3"
	}
	return "local"
}

// ConfigFromEnv reads the storage settings. USE_S3 is strict ("1"/"true" on,
// ""/"0"/"false" off): any other value is an error so a typo cannot silently
// leave uploads on the container's disk.
func ConfigFromEnv(getenv func(string) string) (Config, error) {
	get := func(k string) string { return strings.TrimSpace(getenv(k)) }

	cfg := Config{LocalRoot: get("KG_UPLOAD_DIR")}
	if cfg.LocalRoot == "" {
		cfg.LocalRoot = defaultLocalRoot
	}

	switch strings.ToLower(get("USE_S3")) {
	case "", "0", "false":
		return cfg, nil
	case "1", "true":
		cfg.UseS3 = true
	default:
		return Config{}, fmt.Errorf("USE_S3=%q is not valid: use 1/true or 0/false", getenv("USE_S3"))
	}

	cfg.Bucket = get("AWS_STORAGE_BUCKET_NAME")
	cfg.Region = get("AWS_S3_REGION_NAME")
	cfg.Folder = strings.Trim(get("AWS_MAIN_FOLDER"), "/")
	cfg.AccessKeyID = get("AWS_ACCESS_KEY_ID")
	cfg.SecretAccessKey = get("AWS_SECRET_ACCESS_KEY")

	if cfg.Bucket == "" {
		return Config{}, fmt.Errorf("USE_S3 is on but AWS_STORAGE_BUCKET_NAME is not set")
	}
	if cfg.Region == "" {
		return Config{}, fmt.Errorf("USE_S3 is on but AWS_S3_REGION_NAME is not set")
	}
	if (cfg.AccessKeyID == "") != (cfg.SecretAccessKey == "") {
		return Config{}, fmt.Errorf("set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or neither (IAM role)")
	}
	return cfg, nil
}

// New builds the configured backend.
func New(ctx context.Context, cfg Config) (ObjectStorage, error) {
	if !cfg.UseS3 {
		return NewLocalStorage(cfg.LocalRoot), nil
	}
	return newS3(ctx, cfg)
}
```

- [ ] **Step 6: Implement `S3Storage`**

```go
// ennam.kg.go/internal/storage/s3.go
package storage

import (
	"context"
	"errors"
	"fmt"
	"io"
	"path"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/feature/s3/manager"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
)

// s3API is the slice of S3 the storage uses; tests substitute a fake.
type s3API interface {
	Upload(ctx context.Context, in *s3.PutObjectInput, opts ...func(*manager.Uploader)) (*manager.UploadOutput, error)
	GetObject(ctx context.Context, in *s3.GetObjectInput, opts ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	DeleteObject(ctx context.Context, in *s3.DeleteObjectInput, opts ...func(*s3.Options)) (*s3.DeleteObjectOutput, error)
}

// awsS3 adapts the real client: *s3.Client provides GetObject/DeleteObject,
// the manager provides multipart-aware Upload.
type awsS3 struct {
	*s3.Client
	uploader *manager.Uploader
}

func (a awsS3) Upload(ctx context.Context, in *s3.PutObjectInput, opts ...func(*manager.Uploader)) (*manager.UploadOutput, error) {
	return a.uploader.Upload(ctx, in, opts...)
}

// S3Storage stores objects in one bucket under a fixed key prefix. Objects are
// written without an ACL, so they stay private to the bucket policy.
type S3Storage struct {
	api    s3API
	bucket string
	prefix string
}

func newS3WithAPI(api s3API, bucket, folder string) *S3Storage {
	return &S3Storage{api: api, bucket: bucket, prefix: strings.Trim(folder, "/")}
}

func newS3(ctx context.Context, cfg Config) (*S3Storage, error) {
	opts := []func(*config.LoadOptions) error{config.WithRegion(cfg.Region)}
	if cfg.AccessKeyID != "" {
		opts = append(opts, config.WithCredentialsProvider(
			credentials.NewStaticCredentialsProvider(cfg.AccessKeyID, cfg.SecretAccessKey, "")))
	}
	awsCfg, err := config.LoadDefaultConfig(ctx, opts...)
	if err != nil {
		return nil, fmt.Errorf("load aws config: %w", err)
	}
	client := s3.NewFromConfig(awsCfg)
	return newS3WithAPI(awsS3{Client: client, uploader: manager.NewUploader(client)}, cfg.Bucket, cfg.Folder), nil
}

func (s *S3Storage) objectKey(key string) (string, error) {
	clean := path.Clean(key)
	if key == "" || strings.HasPrefix(clean, "/") || clean == ".." || strings.HasPrefix(clean, "../") {
		return "", fmt.Errorf("storage: invalid key %q", key)
	}
	if s.prefix == "" {
		return clean, nil
	}
	return s.prefix + "/" + clean, nil
}

func (s *S3Storage) Put(ctx context.Context, key string, r io.Reader, contentType string) error {
	k, err := s.objectKey(key)
	if err != nil {
		return err
	}
	in := &s3.PutObjectInput{Bucket: aws.String(s.bucket), Key: aws.String(k), Body: r}
	if contentType != "" {
		in.ContentType = aws.String(contentType)
	}
	if _, err := s.api.Upload(ctx, in); err != nil {
		return fmt.Errorf("s3 put: %w", err)
	}
	return nil
}

func (s *S3Storage) Open(ctx context.Context, key string) (io.ReadCloser, error) {
	k, err := s.objectKey(key)
	if err != nil {
		return nil, err
	}
	out, err := s.api.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(s.bucket), Key: aws.String(k)})
	if err != nil {
		var noKey *types.NoSuchKey
		if errors.As(err, &noKey) {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("s3 get: %w", err)
	}
	return out.Body, nil
}

func (s *S3Storage) Delete(ctx context.Context, key string) error {
	k, err := s.objectKey(key)
	if err != nil {
		return err
	}
	if _, err := s.api.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: aws.String(s.bucket), Key: aws.String(k)}); err != nil {
		return fmt.Errorf("s3 delete: %w", err)
	}
	return nil
}
```

- [ ] **Step 7: Run to verify it passes**

Run: `cd ennam.kg.go && go vet ./internal/storage/ && go test ./internal/storage/ -v -race`
Expected: PASS (Task 1 tests + 8 new test functions).

- [ ] **Step 8: Commit**

```bash
git -C ennam.kg.go add go.mod go.sum internal/storage
git -C ennam.kg.go commit -m "feat(storage): add S3 backend, env config and factory

USE_S3 is strict so a typo cannot silently keep uploads on local disk.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Wire `FileUploadService`, `Download` handler and `main.go`

**Files:**
- Modify: `ennam.kg.go/internal/service/file_upload.go` (imports; struct `:62-72`; constructor `:74-97`; `handleOneFile` `:176-233` and the cleanup at `:227`,`:270`; `ResolveStoredPath` `:314-317`; `DeleteUpload` `:319-334`)
- Modify: `ennam.kg.go/internal/handler/ingest_upload.go` (`Download`, `:120-141`)
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (`:721-733`)
- Test: `ennam.kg.go/internal/service/file_upload_test.go`, new `ennam.kg.go/internal/service/file_upload_storage_test.go`, new `ennam.kg.go/internal/handler/ingest_upload_download_test.go`

**Interfaces:**
- Consumes: `storage.ObjectStorage`, `storage.ErrNotFound`, `storage.NewLocalStorage`, `storage.ConfigFromEnv`, `storage.New`, `Config.Backend()` (Tasks 1–2).
- Produces:
  - `NewFileUploadService(uploads uploadedFileStore, draftContent draftContentStore, draftIngest draftIngestionService, extractPub extractUploadPublisher, settingsReader settingsReader, objects storage.ObjectStorage, logger *slog.Logger) *FileUploadService`
  - `func (s *FileUploadService) OpenUpload(ctx context.Context, file *models.UploadedFile) (io.ReadCloser, error)` — returns `storage.ErrNotFound` when absent. **Replaces** `ResolveStoredPath`.

- [ ] **Step 1: Adapt the existing test helper and add a failing-create switch**

In `internal/service/file_upload_test.go`:
- add a field `createErr error` to `mockUploadedFileStore`, and make `Create` return it first:

```go
func (m *mockUploadedFileStore) Create(_ context.Context, f *models.UploadedFile) error {
	if m.createErr != nil {
		return m.createErr
	}
	f.ID = "upload-1"
	m.created = f
	return nil
}
```
- change `newTestUploadSvc` to pass storage instead of a directory (add import `"github.com/ennam/ennam-kg/internal/storage"`):

```go
		storage.NewLocalStorage(t.TempDir()),
		nil,
```
(replacing `t.TempDir(),` / `nil,` — the sixth argument is now the `ObjectStorage`).

- [ ] **Step 2: Write the failing service tests**

```go
// ennam.kg.go/internal/service/file_upload_storage_test.go
package service

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"mime/multipart"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/storage"
)

type fakeObjectStorage struct {
	puts    map[string][]byte
	deleted []string
	putErr  error
}

func newFakeObjectStorage() *fakeObjectStorage { return &fakeObjectStorage{puts: map[string][]byte{}} }

func (f *fakeObjectStorage) Put(_ context.Context, key string, r io.Reader, _ string) error {
	b, err := io.ReadAll(r)
	if err != nil {
		return err
	}
	if f.putErr != nil {
		return f.putErr
	}
	f.puts[key] = b
	return nil
}

func (f *fakeObjectStorage) Open(_ context.Context, key string) (io.ReadCloser, error) {
	b, ok := f.puts[key]
	if !ok {
		return nil, storage.ErrNotFound
	}
	return io.NopCloser(strings.NewReader(string(b))), nil
}

func (f *fakeObjectStorage) Delete(_ context.Context, key string) error {
	f.deleted = append(f.deleted, key)
	delete(f.puts, key)
	return nil
}

func newSvcWithStorage(uploads *mockUploadedFileStore, objs storage.ObjectStorage) *FileUploadService {
	return NewFileUploadService(
		uploads,
		&mockDraftContentStore2{},
		&mockDraftIngestService2{},
		&mockExtractPublisher{},
		&mockSettingsReader{data: map[string]json.RawMessage{}},
		objs,
		nil,
	)
}

func TestUpload_StoresObjectUnderRelativeStoredPath(t *testing.T) {
	objs := newFakeObjectStorage()
	uploads := &mockUploadedFileStore{}
	svc := newSvcWithStorage(uploads, objs)

	fh := buildMemoryFileHeader(t, "report.md", []byte("# hi"))
	if _, err := svc.HandleUpload(context.Background(), "proj-1", []*multipart.FileHeader{fh}, UploadOptions{UploadedBy: "u"}); err != nil {
		t.Fatalf("HandleUpload: %v", err)
	}
	if len(objs.puts) != 1 {
		t.Fatalf("puts = %v, want exactly one object", objs.puts)
	}
	sp := uploads.created.StoredPath
	if !strings.HasPrefix(sp, "proj-1/") || !strings.HasSuffix(sp, "/report.md") {
		t.Errorf("stored_path = %q, want proj-1/<upload>/report.md", sp)
	}
	if string(objs.puts[sp]) != "# hi" {
		t.Errorf("object under %q = %q", sp, objs.puts[sp])
	}
}

func TestUpload_PutFailureCreatesNoRecord(t *testing.T) {
	objs := newFakeObjectStorage()
	objs.putErr = errors.New("s3 down")
	uploads := &mockUploadedFileStore{}
	svc := newSvcWithStorage(uploads, objs)

	fh := buildMemoryFileHeader(t, "a.md", []byte("x"))
	if _, err := svc.HandleUpload(context.Background(), "proj-1", []*multipart.FileHeader{fh}, UploadOptions{}); err == nil {
		t.Fatal("HandleUpload succeeded, want the storage error")
	}
	if uploads.created != nil {
		t.Error("a DB record was created although the object was not stored")
	}
}

func TestUpload_RecordFailureDeletesTheObject(t *testing.T) {
	objs := newFakeObjectStorage()
	uploads := &mockUploadedFileStore{createErr: errors.New("db down")}
	svc := newSvcWithStorage(uploads, objs)

	fh := buildMemoryFileHeader(t, "a.md", []byte("x"))
	if _, err := svc.HandleUpload(context.Background(), "proj-1", []*multipart.FileHeader{fh}, UploadOptions{}); err == nil {
		t.Fatal("HandleUpload succeeded, want the db error")
	}
	if len(objs.puts) != 0 || len(objs.deleted) != 1 {
		t.Errorf("object left behind: puts=%v deleted=%v", objs.puts, objs.deleted)
	}
}

func TestDeleteUpload_RemovesTheObject(t *testing.T) {
	objs := newFakeObjectStorage()
	uploads := &mockUploadedFileStore{}
	svc := newSvcWithStorage(uploads, objs)
	fh := buildMemoryFileHeader(t, "a.md", []byte("x"))
	_, _ = svc.HandleUpload(context.Background(), "proj-1", []*multipart.FileHeader{fh}, UploadOptions{})
	stored := uploads.created.StoredPath

	if err := svc.DeleteUpload(context.Background(), "proj-1", "upload-1"); err != nil {
		t.Fatalf("DeleteUpload: %v", err)
	}
	if len(objs.deleted) != 1 || objs.deleted[0] != stored {
		t.Errorf("deleted = %v, want [%q]", objs.deleted, stored)
	}
}

func TestOpenUpload_ReturnsContentAndErrNotFound(t *testing.T) {
	objs := newFakeObjectStorage()
	uploads := &mockUploadedFileStore{}
	svc := newSvcWithStorage(uploads, objs)
	fh := buildMemoryFileHeader(t, "a.md", []byte("body"))
	_, _ = svc.HandleUpload(context.Background(), "proj-1", []*multipart.FileHeader{fh}, UploadOptions{})

	rc, err := svc.OpenUpload(context.Background(), uploads.created)
	if err != nil {
		t.Fatalf("OpenUpload: %v", err)
	}
	b, _ := io.ReadAll(rc)
	rc.Close()
	if string(b) != "body" {
		t.Errorf("got %q", b)
	}

	missing := *uploads.created
	missing.StoredPath = "proj-1/gone/a.md"
	if _, err := svc.OpenUpload(context.Background(), &missing); !errors.Is(err, storage.ErrNotFound) {
		t.Errorf("err = %v, want ErrNotFound", err)
	}
}
```

Also add a test for the size cap. A fixed-size `fh` cannot exceed the cap through `HandleUpload` (it rejects by `fh.Size` first), so the cap-on-read path is covered by a unit test of the counting reader (Step 4 adds `countingReader`):

```go
func TestCountingReader_CountsBytesAndHonoursLimit(t *testing.T) {
	cr := &countingReader{r: io.LimitReader(strings.NewReader("0123456789"), 4)}
	b, _ := io.ReadAll(cr)
	if string(b) != "0123" || cr.n != 4 {
		t.Errorf("got %q n=%d, want 0123 n=4", b, cr.n)
	}
}
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/service/ -run 'TestUpload_|TestDeleteUpload|TestOpenUpload|TestCountingReader|TestUploadMd|TestUploadTxt' 2>&1 | tail -15`
Expected: FAIL (compile errors: constructor signature, `OpenUpload`, `countingReader`).

- [ ] **Step 4: Implement the service changes**

In `internal/service/file_upload.go`:

1. Imports: remove `"os"`; add `"path"` and `"github.com/ennam/ennam-kg/internal/storage"` (keep `"path/filepath"`, still used by `sanitizeFilename` and `filepath.Ext`).
2. Struct and constructor — replace `storageRoot string` with `objects storage.ObjectStorage`:

```go
type FileUploadService struct {
	uploads        uploadedFileStore
	draftContent   draftContentStore
	draftIngest    draftIngestionService
	extractPub     extractUploadPublisher
	settingsReader settingsReader
	objects        storage.ObjectStorage
	logger         *slog.Logger
}

func NewFileUploadService(
	uploads uploadedFileStore,
	draftContent draftContentStore,
	draftIngest draftIngestionService,
	extractPub extractUploadPublisher,
	settingsReader settingsReader,
	objects storage.ObjectStorage,
	logger *slog.Logger,
) *FileUploadService {
	if logger == nil {
		logger = slog.Default()
	}
	return &FileUploadService{
		uploads:        uploads,
		draftContent:   draftContent,
		draftIngest:    draftIngest,
		extractPub:     extractPub,
		settingsReader: settingsReader,
		objects:        objects,
		logger:         logger,
	}
}
```
(delete the `strings.TrimSpace(storageRoot)` default block.)

3. In `handleOneFile`, replace everything from `relPath := filepath.Join(...)` through the `mimeType` assignment (the `MkdirAll`, `fh.Open`, `OpenFile`, `io.Copy`, size check) with:

```go
	relPath := path.Join(projectID, uploadID, sanitizeFilename(fh.Filename))

	src, err := fh.Open()
	if err != nil {
		return nil, fmt.Errorf("open upload file: %w", err)
	}
	defer src.Close()

	mimeType := fh.Header.Get("Content-Type")
	if mimeType == "" {
		mimeType = mimeTypeForExt(ext)
	}

	// Read at most maxFileBytes+1 so an oversize body is detected without
	// buffering it; countingReader reports how much was actually stored.
	counter := &countingReader{r: io.LimitReader(src, maxFileBytes+1)}
	if err := s.objects.Put(ctx, relPath, counter, mimeType); err != nil {
		return nil, fmt.Errorf("store upload file: %w", err)
	}
	written := counter.n
	if written > maxFileBytes {
		s.deleteObject(ctx, relPath)
		return nil, fmt.Errorf("%w: %s", ErrUploadTooLarge, fh.Filename)
	}
```
and replace both remaining `_ = os.Remove(absPath)` (after `s.uploads.Create` fails, and after `UpsertFromIngestion` fails) with `s.deleteObject(ctx, relPath)`.

4. Replace `ResolveStoredPath` and `DeleteUpload`'s removal, and add the helpers:

```go
// OpenUpload streams a stored upload; it returns storage.ErrNotFound when the
// object is missing (e.g. rows created before S3 storage).
func (s *FileUploadService) OpenUpload(ctx context.Context, file *models.UploadedFile) (io.ReadCloser, error) {
	return s.objects.Open(ctx, file.StoredPath)
}

// DeleteUpload soft-deletes the record and removes the stored object.
func (s *FileUploadService) DeleteUpload(ctx context.Context, projectID, uploadID string) error {
	file, err := s.uploads.GetByID(ctx, projectID, uploadID)
	if err != nil {
		return err
	}
	if err := s.uploads.SoftDelete(ctx, projectID, uploadID); err != nil {
		return err
	}
	s.deleteObject(ctx, file.StoredPath)
	return nil
}

// deleteObject removes an object best-effort: a leftover object is logged,
// never allowed to fail the request that already succeeded or failed on its own.
func (s *FileUploadService) deleteObject(ctx context.Context, key string) {
	if err := s.objects.Delete(ctx, key); err != nil {
		s.logger.Warn("failed to remove upload object", "key", key, "error", err)
	}
}

// countingReader counts the bytes read through it.
type countingReader struct {
	r io.Reader
	n int64
}

func (c *countingReader) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n += int64(n)
	return n, err
}
```

- [ ] **Step 5: Run service tests**

Run: `cd ennam.kg.go && go build ./... 2>&1 | head; go test ./internal/service/ -run 'FileUpload|Upload|OpenUpload|CountingReader|Classify' -race`
Expected: the service package compiles and these tests PASS (`go build ./...` may still fail in `cmd/kg-server` and `handler` until Steps 6–8; that is expected).

- [ ] **Step 6: Write the failing handler test**

```go
// ennam.kg.go/internal/handler/ingest_upload_download_test.go
package handler

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
	"github.com/ennam/ennam-kg/internal/storage"
	"github.com/ennam/ennam-kg/internal/store"
)

// uploadsOnlyStore implements the service's unexported uploadedFileStore;
// Download only needs GetByID.
type uploadsOnlyStore struct{ file *models.UploadedFile }

func (u *uploadsOnlyStore) Create(context.Context, *models.UploadedFile) error { return nil }
func (u *uploadsOnlyStore) GetByID(context.Context, string, string) (*models.UploadedFile, error) {
	return u.file, nil
}
func (u *uploadsOnlyStore) List(context.Context, string, store.UploadedFileListFilters) ([]*models.UploadedFile, int, error) {
	return nil, 0, nil
}
func (u *uploadsOnlyStore) SumActiveBytes(context.Context, string) (int64, error) { return 0, nil }
func (u *uploadsOnlyStore) SetDraftNodeID(context.Context, string, string, string) error {
	return nil
}
func (u *uploadsOnlyStore) MarkContentExtracted(context.Context, string, string) error { return nil }
func (u *uploadsOnlyStore) SoftDelete(context.Context, string, string) error          { return nil }

func downloadHandler(t *testing.T, file *models.UploadedFile, objs storage.ObjectStorage) *http.ServeMux {
	t.Helper()
	svc := service.NewFileUploadService(&uploadsOnlyStore{file: file}, nil, nil, nil, nil, objs, nil)
	mux := http.NewServeMux()
	NewIngestUploadHandler(svc, nil).RegisterRoutes(mux)
	return mux
}

func TestDownload_StreamsStoredFileWithItsMimeType(t *testing.T) {
	objs := storage.NewLocalStorage(t.TempDir())
	if err := objs.Put(context.Background(), "p/u/doc.pdf", strings.NewReader("%PDF-body"), "application/pdf"); err != nil {
		t.Fatal(err)
	}
	mt := "application/pdf"
	mux := downloadHandler(t, &models.UploadedFile{ID: "u", ProjectID: "p", StoredPath: "p/u/doc.pdf", MimeType: &mt}, objs)

	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/projects/p/uploads/u/download", nil))

	body, _ := io.ReadAll(rec.Body)
	if rec.Code != http.StatusOK || string(body) != "%PDF-body" {
		t.Fatalf("status=%d body=%q", rec.Code, body)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/pdf" {
		t.Errorf("Content-Type = %q", ct)
	}
}

func TestDownload_MissingObjectIs404NotA500(t *testing.T) {
	objs := storage.NewLocalStorage(t.TempDir()) // nothing stored: models a pre-S3 row
	mux := downloadHandler(t, &models.UploadedFile{ID: "u", ProjectID: "p", StoredPath: "p/u/old.pdf"}, objs)

	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/projects/p/uploads/u/download", nil))

	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rec.Code)
	}
}

func TestDownload_FileWithoutMimeTypeFallsBackToOctetStream(t *testing.T) {
	objs := storage.NewLocalStorage(t.TempDir())
	_ = objs.Put(context.Background(), "p/u/blob", strings.NewReader("x"), "")
	mux := downloadHandler(t, &models.UploadedFile{ID: "u", ProjectID: "p", StoredPath: "p/u/blob"}, objs)

	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/projects/p/uploads/u/download", nil))

	if ct := rec.Header().Get("Content-Type"); ct != "application/octet-stream" {
		t.Errorf("Content-Type = %q", ct)
	}
}
```

- [ ] **Step 7: Implement the handler change**

Replace the last two lines of `Download` (`path := h.svc.ResolveStoredPath(file)` / `http.ServeFile(w, r, path)`) with the code below, and add `"io"` and `"github.com/ennam/ennam-kg/internal/storage"` to the imports (keep `errors`, already imported):

```go
	rc, err := h.svc.OpenUpload(r.Context(), file)
	if err != nil {
		if errors.Is(err, storage.ErrNotFound) {
			errorResponse(w, http.StatusNotFound, "file not found")
			return
		}
		h.logger.Error("open upload failed", "upload_id", uploadID, "error", err)
		errorResponse(w, http.StatusInternalServerError, "download failed")
		return
	}
	defer rc.Close()

	contentType := "application/octet-stream"
	if file.MimeType != nil && *file.MimeType != "" {
		contentType = *file.MimeType
	}
	w.Header().Set("Content-Type", contentType)
	if _, err := io.Copy(w, rc); err != nil {
		h.logger.Warn("download stream interrupted", "upload_id", uploadID, "error", err)
	}
```

- [ ] **Step 8: Wire `main.go`**

Replace the `uploadRoot := os.Getenv("KG_UPLOAD_DIR")` block (lines ~721-725) and the `uploadRoot,` constructor argument:

```go
	storageCfg, err := storage.ConfigFromEnv(os.Getenv)
	if err != nil {
		logger.Error("invalid upload storage config", "error", err)
		os.Exit(1)
	}
	uploadObjects, err := storage.New(context.Background(), storageCfg)
	if err != nil {
		logger.Error("upload storage init failed", "backend", storageCfg.Backend(), "error", err)
		os.Exit(1)
	}
	logger.Info("upload storage ready", "backend", storageCfg.Backend())
	uploadSvc := service.NewFileUploadService(
		uploadStore,
		draftNodeStore,
		draftSvc,
		ingestionPub,
		service.NewSettingsValueReader(settingsStore),
		uploadObjects,
		logger,
	)
```
Add the import `"github.com/ennam/ennam-kg/internal/storage"`. If `err` is already declared in that scope, change `:=` to `=` for the first assignment as the compiler directs. Then check no other caller exists: `grep -rn "NewFileUploadService(" ennam.kg.go --include='*.go' | grep -v '/.claude/'`.

- [ ] **Step 9: Run everything**

Run: `cd ennam.kg.go && go build ./... && go vet ./... && go test ./internal/storage/ ./internal/service/ ./internal/handler/ -race 2>&1 | tail -15`
Expected: build and vet clean; PASS. If a handler-package test already defines `uploadsOnlyStore` or another helper name used here, rename the new one.

- [ ] **Step 10: Commit**

```bash
git -C ennam.kg.go add internal/service internal/handler/ingest_upload.go internal/handler/ingest_upload_download_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(upload): store uploads through ObjectStorage (local or S3)

FileUploadService and the download handler no longer touch the filesystem
directly. Missing objects download as 404; failed or oversize uploads delete
the stored object.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Python — `download_upload` and worker temp-file handling

**Files:**
- Modify: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` (add method after `update_draft_content`, `:317-337`)
- Create: `ennam.kg.python/src/ennam_kg/upload_files.py`
- Modify: `ennam.kg.python/src/ennam_kg/worker.py` (`handle_extract_upload`, `:336-358`)
- Test: `ennam.kg.python/packages/ennam-kg-indexer/tests/test_kg_client_upload.py`, `ennam.kg.python/tests/test_upload_files.py`

**Interfaces:**
- Consumes: Go route `GET /api/v1/projects/{id}/uploads/{uploadId}/download` (Task 3), `KGClientError`.
- Produces:
  - `async def KGClient.download_upload(self, project_id: str, upload_id: str, dest_path: Path) -> None`
  - `local_upload_file(kg_client, *, project_id: str, upload_id: str, stored_path: str, upload_dir: str)` — async context manager yielding a `Path`.

- [ ] **Step 1: Write the failing client tests**

```python
# ennam.kg.python/packages/ennam-kg-indexer/tests/test_kg_client_upload.py
from pathlib import Path

import httpx
import pytest

from ennam_kg_indexer.kg_client.client import KGClient, KGClientError


def _client(handler) -> tuple[KGClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    return KGClient(base_url="http://test", api_key="worker-key", http_client=http), http


@pytest.mark.asyncio
async def test_download_upload_streams_bytes_to_dest_with_bearer_auth(tmp_path: Path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"%PDF-" + b"x" * 100_000)

    client, http = _client(handler)
    dest = tmp_path / "doc.pdf"
    async with http:
        await client.download_upload("proj-1", "up-1", dest)

    assert seen["path"] == "/api/v1/projects/proj-1/uploads/up-1/download"
    assert seen["auth"] == "Bearer worker-key"
    assert dest.read_bytes() == b"%PDF-" + b"x" * 100_000


@pytest.mark.asyncio
async def test_download_upload_zero_byte_file(tmp_path: Path):
    client, http = _client(lambda r: httpx.Response(200, content=b""))
    dest = tmp_path / "empty.txt"
    async with http:
        await client.download_upload("p", "u", dest)
    assert dest.exists() and dest.read_bytes() == b""


@pytest.mark.asyncio
async def test_download_upload_404_raises_and_leaves_no_file(tmp_path: Path):
    client, http = _client(lambda r: httpx.Response(404, json={"error": "file not found"}))
    dest = tmp_path / "doc.pdf"
    async with http:
        with pytest.raises(KGClientError) as exc:
            await client.download_upload("p", "u", dest)
    assert exc.value.status_code == 404
    assert not dest.exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.python && uv run pytest packages/ennam-kg-indexer/tests/test_kg_client_upload.py -v`
Expected: FAIL (`AttributeError: 'KGClient' object has no attribute 'download_upload'`).

- [ ] **Step 3: Implement `download_upload`**

In `client.py`, add `from pathlib import Path` to the imports and this method after `update_draft_content`:

```python
    async def download_upload(self, project_id: str, upload_id: str, dest_path: Path) -> None:
        """Stream an uploaded file from the Go API into dest_path.

        Raises KGClientError on a non-2xx status and leaves no partial file.
        """
        async with self._http_client.stream(
            "GET",
            f"/api/v1/projects/{project_id}/uploads/{upload_id}/download",
            headers=self._auth_header(),
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise KGClientError(
                    status_code=response.status_code,
                    detail=body.decode("utf-8", errors="replace"),
                )
            try:
                with dest_path.open("wb") as fh:
                    async for chunk in response.aiter_bytes():
                        fh.write(chunk)
            except BaseException:
                dest_path.unlink(missing_ok=True)
                raise
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd ennam.kg.python && uv run pytest packages/ennam-kg-indexer/tests/test_kg_client_upload.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Write the failing helper tests**

```python
# ennam.kg.python/tests/test_upload_files.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ennam_kg.upload_files import local_upload_file


def _client_writing(content: bytes) -> AsyncMock:
    client = AsyncMock()

    async def download(project_id, upload_id, dest_path):
        Path(dest_path).write_bytes(content)

    client.download_upload.side_effect = download
    return client


@pytest.mark.asyncio
async def test_downloads_to_a_temp_file_keeping_the_extension():
    client = _client_writing(b"pdf-bytes")
    async with local_upload_file(
        client, project_id="p", upload_id="u", stored_path="p/u/Report 2026.pdf", upload_dir="/unused"
    ) as path:
        assert path.suffix == ".pdf"
        assert path.read_bytes() == b"pdf-bytes"
        seen = path
    client.download_upload.assert_awaited_once()
    assert not seen.exists(), "temp file must be removed after use"


@pytest.mark.asyncio
async def test_temp_file_is_removed_even_when_the_body_raises():
    client = _client_writing(b"x")
    seen: list[Path] = []
    with pytest.raises(RuntimeError):
        async with local_upload_file(
            client, project_id="p", upload_id="u", stored_path="p/u/a.txt", upload_dir="/unused"
        ) as path:
            seen.append(path)
            raise RuntimeError("extraction failed")
    assert seen and not seen[0].exists()


@pytest.mark.asyncio
async def test_without_upload_id_falls_back_to_the_disk_path(tmp_path: Path):
    client = AsyncMock()
    async with local_upload_file(
        client, project_id="p", upload_id="", stored_path="p/u/a.txt", upload_dir=str(tmp_path)
    ) as path:
        assert path == tmp_path / "p/u/a.txt"
    client.download_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_error_propagates_and_leaves_nothing():
    client = AsyncMock()
    client.download_upload.side_effect = RuntimeError("404")
    with pytest.raises(RuntimeError, match="404"):
        async with local_upload_file(
            client, project_id="p", upload_id="u", stored_path="p/u/a.txt", upload_dir="/unused"
        ):
            pytest.fail("body must not run when the download fails")
```

- [ ] **Step 6: Run to verify they fail**

Run: `cd ennam.kg.python && uv run pytest tests/test_upload_files.py -v`
Expected: FAIL (`ModuleNotFoundError: ennam_kg.upload_files`).

- [ ] **Step 7: Implement the helper**

```python
# ennam.kg.python/src/ennam_kg/upload_files.py
"""Give the extraction code a local file for an uploaded document.

kg-server owns where uploads live (local disk or S3), so the worker fetches the
file through the Go API instead of reading a shared volume.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any


@asynccontextmanager
async def local_upload_file(
    kg_client: Any,
    *,
    project_id: str,
    upload_id: str,
    stored_path: str,
    upload_dir: str,
) -> AsyncIterator[Path]:
    """Yield a local Path holding the upload; remove any temp copy on exit.

    Without an upload_id (messages queued before the S3 change) the old shared
    disk path is used as-is.
    """
    if not upload_id:
        yield Path(upload_dir) / stored_path
        return

    with tempfile.TemporaryDirectory(prefix="kg-upload-") as tmp:
        # Keep the original file name: extraction picks its parser by extension.
        dest = Path(tmp) / Path(stored_path).name
        await kg_client.download_upload(project_id, upload_id, dest)
        yield dest
```

- [ ] **Step 8: Use it in the worker**

In `worker.py`, add `from ennam_kg.upload_files import local_upload_file` with the other `ennam_kg` imports, then replace lines `file_path = Path(settings.kg_upload_dir) / stored_path` through the `structured_fields = …` assignment with:

```python
        logger.info(
            "Extracting upload text: project=%s draft=%s upload=%s stored_path=%s",
            project_id,
            draft_id,
            upload_id,
            stored_path,
        )
        async with local_upload_file(
            kg_client,
            project_id=project_id,
            upload_id=upload_id,
            stored_path=stored_path,
            upload_dir=settings.kg_upload_dir,
        ) as file_path:
            content_raw, content_format = await asyncio.to_thread(extract_file_text, file_path)
            structured_fields = await asyncio.to_thread(extract_structured_fields_for_file, file_path)
```
Leave everything after (`recovered_section = …`) unchanged and outside the `async with`. Remove the now-unused `from pathlib import Path` import only if `ruff` reports it unused.

- [ ] **Step 9: Run Python tests and lint**

Run: `cd ennam.kg.python && uv run pytest tests/test_upload_files.py tests/test_worker_extract_gate.py packages/ennam-kg-indexer/tests/test_kg_client_upload.py -v && uv run ruff check src/ennam_kg/upload_files.py src/ennam_kg/worker.py packages/ennam-kg-indexer/src`
Expected: PASS and ruff clean. If `test_worker_extract_gate.py` fails because its message has an `upload_id` and the mock client now needs `download_upload`, the mock is already an `AsyncMock`, so it should pass; if it does not, make the failing test's `mock_kg_client.download_upload` an `AsyncMock()` rather than weakening the new code.

- [ ] **Step 10: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/upload_files.py src/ennam_kg/worker.py packages/ennam-kg-indexer/src packages/ennam-kg-indexer/tests/test_kg_client_upload.py tests/test_upload_files.py
git -C ennam.kg.python commit -m "feat(worker): fetch uploads through the Go API instead of a shared volume

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Configuration, docs and spec alignment

**Files:**
- Modify: `.env.release.example` (workspace root)
- Modify: `docker-compose.release.yml` (kg-server `environment`, near `KG_UPLOAD_DIR` at `:99`)
- Modify: `envfiles/kg-server.env` (untracked local copy of the prod env; append, leave secrets blank)
- Modify: `docs/superpowers/specs/2026-10-01-s3-upload-storage-design.md`

**Interfaces:**
- Consumes: the env contract from Task 2 (`USE_S3`, `AWS_STORAGE_BUCKET_NAME`, `AWS_MAIN_FOLDER`, `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).
- Produces: documented, copy-pasteable config for operators.

- [ ] **Step 1: Document the variables in `.env.release.example`**

Append:

```bash
# --- Upload storage (kg-server only) ---
# Default: files are kept on the container's disk under KG_UPLOAD_DIR.
# USE_S3=1 stores new uploads in S3 instead (objects stay private; downloads go
# through the API). Accepted: 1/true (on), 0/false/empty (off). Anything else
# stops kg-server at startup.
# With USE_S3=1 the bucket and region are required. Leave the two AWS key vars
# empty to use the IAM role of the task/instance; set both or neither.
USE_S3=0
AWS_STORAGE_BUCKET_NAME=
AWS_MAIN_FOLDER=media/daab
AWS_S3_REGION_NAME=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

- [ ] **Step 2: Pass them to kg-server in `docker-compose.release.yml`**

In the `kg-server` service `environment:` block, after `KG_UPLOAD_DIR: /app/data/uploads`, add:

```yaml
      USE_S3: ${USE_S3:-0}
      AWS_STORAGE_BUCKET_NAME: ${AWS_STORAGE_BUCKET_NAME:-}
      AWS_MAIN_FOLDER: ${AWS_MAIN_FOLDER:-media/daab}
      AWS_S3_REGION_NAME: ${AWS_S3_REGION_NAME:-}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
```
Do not add them to the worker or indexer.

- [ ] **Step 3: Append the prod values to `envfiles/kg-server.env`** (secrets left blank for the owner to fill)

```bash
USE_S3=1
AWS_STORAGE_BUCKET_NAME=devshared-ap-southeast-1-public-storage
AWS_MAIN_FOLDER=media/daab
AWS_S3_REGION_NAME=ap-southeast-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```
Ensure the file ends with a newline before appending. This file is untracked: do not commit it.

- [ ] **Step 4: Align the spec with the plan's three decisions**

In `docs/superpowers/specs/2026-10-01-s3-upload-storage-design.md`: remove the `size int64` argument from the `Put` signature in §4.1; in §4.4 replace "sets `Content-Type` … and `Content-Disposition`" with "sets `Content-Type` (stored mime type, else `application/octet-stream`) and does not set `Content-Disposition`, matching the previous `http.ServeFile` behaviour"; in §4.2 replace "`USE_S3` of `1` or `true` selects `S3Storage`, anything else `LocalStorage`" with "`1`/`true` (case-insensitive) selects `S3Storage`; `""`/`0`/`false` select `LocalStorage`; any other value is a startup error".

- [ ] **Step 5: Verify**

Run: `docker compose -f docker-compose.release.yml config >/dev/null && echo compose-ok; grep -c "USE_S3" .env.release.example docker-compose.release.yml`
Expected: `compose-ok`, and each file reports at least 1.

- [ ] **Step 6: Commit (workspace repo)**

```bash
git add .env.release.example docker-compose.release.yml docs/superpowers/specs/2026-10-01-s3-upload-storage-design.md docs/superpowers/plans/2026-10-01-s3-upload-storage.md
git commit -m "docs(config): document S3 upload storage settings and align the spec

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Manual smoke test (after all tasks; needs real AWS keys — owner decides)

1. Local, with `USE_S3=1` and the bucket/region/keys in a local env: start kg-server and upload a small `.md` through the API.
2. Confirm the object exists at `s3://devshared-ap-southeast-1-public-storage/media/daab/<project>/<upload>/<file>` and is **not** publicly readable (anonymous `curl` of the object URL returns 403).
3. `GET /api/v1/projects/<id>/uploads/<uploadId>/download` returns the content; the worker extracts it; `DELETE` removes the object.
4. Fail-loud check: start with `USE_S3=yes` → the server exits with an error naming `USE_S3`.

## Self-review notes

- **Spec coverage:** §4.1 → Tasks 1–2; §4.2 → Task 2 (config) + Task 5 (docs/compose/env); §4.3 → Task 3; §4.4 → Task 3; §4.5 → Task 4; §4.6 errors → Tasks 3–4 tests; §4.7 IAM/bucket → manual smoke step 2 and spec (owner action); §5 tests → each task; §6 rollout → spec only (operational).
- **Types:** `ObjectStorage`/`ErrNotFound` (Task 1) are used unchanged in Tasks 2–3; `OpenUpload` (Task 3) is the only new service method and replaces `ResolveStoredPath`; `download_upload`/`local_upload_file` signatures match between Task 4 steps.
