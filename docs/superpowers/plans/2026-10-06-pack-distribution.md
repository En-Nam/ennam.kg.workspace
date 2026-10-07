# Pack Distribution (own repo, registry service, install/update from DAAB and LAAM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make industry packs a versioned, separately released artifact that admins install, update and roll back from the DAAB dashboard and the LAAM settings, without rebuilding DAAB or LAAM, with DAAB and LAAM never silently running different pack versions.

**Architecture:** Packs move to their own git repo `ennam.kg.packs`; CI publishes one tarball per pack version to a small Go service `kg-pack-registry` (bearer tokens, storage behind an interface, filesystem first so DevOps can swap in S3). DAAB (Go) and LAAM (TypeScript) each get a "fetch" client that downloads a version, verifies sha256, extracts safely into `PACKS_DIR` keeping previous versions for rollback. DAAB gets a `RegistryHolder` so a new/changed pack loads without a restart. Both products get an admin screen for install/update/rollback. Project-level enable/disable (`pack_install`) is unchanged.

**Tech Stack:** Go (net/http, slog, existing intel packages), Next.js (DAAB dashboard; LAAM 16 App Router + Drizzle + vitest), GitHub Actions, Docker/compose.

**Spec:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (§5 pack ownership), decisions in conversation 2026-10-05/06 summarised under "Decisions" below.

## Global Constraints

- **No DB schema changes** in DAAB or LAAM (no migrations, no new tables/columns; LAAM `user` table untouched). Versions are tracked on disk and in the existing `pack_install.version`.
- **Nothing is deployed or pushed by agents.** No `git push`, no `docker compose up/restart` of the existing stack, no edits to any `.env` or to files in `envfiles/` (never read their values). Do not run anything against the real DBs (:5500 laam, DAAB :5433 only for Go DB tests via the documented env var, never :5432).
- **Security rules (apply to every task):** tarballs are untrusted input: reject absolute paths, `..`, symlinks/hardlinks, device files, paths outside the pack's own top-level directory; cap compressed size at 20 MiB and total extracted size at 100 MiB and file count at 2000; verify sha256 before extraction; a version is **immutable** (publishing/installing the same key+version with a different sha256 is refused); tokens come only from environment variables, are compared in constant time, and never appear in logs, responses or error messages; the UI never accepts a source URL (the operator configures `PACKS_SOURCE`).
- **On-disk layout:** `PACKS_DIR/<key>/` is the active pack (directory name must equal the pack key: the loaders require it); previous versions live under `PACKS_DIR/_versions/<key>/<version>/` (names starting with `_` or `.` are skipped by both loaders); staging under `PACKS_DIR/_staging/`. Swapping the active version never leaves a half-written `<key>/`; a failed install leaves the previous version active.
- **Env variable names (exact):** registry service `KG_PACKS_STORAGE_DIR`, `KG_PACKS_READ_TOKEN`, `KG_PACKS_PUBLISH_TOKEN`, `KG_PACKS_PORT` (default 8090); clients (DAAB and LAAM) `PACKS_DIR` (existing), `PACKS_SOURCE` (registry base URL), `PACKS_TOKEN` (read token). CI secrets: `PACKS_REGISTRY_URL`, `PACKS_PUBLISH_TOKEN`.
- **UI for non-technical users** (all new screens): everyday words, no jargon (no "tarball", "sha256", "registry" on screen; say "template", "version", "update"), plain error messages with the next step, confirm before update/rollback, empty states, no horizontal scroll at 375px, keyboard accessible. LAAM strings in vi/en/zh via a new dictionary; the DAAB dashboard is inline English like the rest of that app.
- Code comments and commit messages in English; commit trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Commit per repo with explicit `git add <paths>` (never `git add -A`; unrelated modified files exist in the workspace and sub-repos).
- TDD where a harness exists (Go, LAAM). `ennam.kg.next` has no test infra: verify with lint on touched files and `npm run build`.
- Match existing conventions: Go services follow `cmd/kg-bridge` + `internal/bridge` (slog, `signal.NotifyContext` shutdown, `/healthz` and `/readyz`, `requireBearerV2`-style constant-time bearer middleware).

## Decisions (2026-10-06)

1. History of `packs/` is preserved with `git filter-repo` (installed at `/opt/homebrew/bin/git-filter-repo`; `git subtree` is unavailable). `_projects/` (per-customer mapping) is **excluded** from the new repo and stays in the workspace.
2. Registry API contract (exact; all tasks code against it):
   - `GET /v1/catalog` (read token) -> `{"packs":[{"key","display_name","extends":[...],"latest":"0.2.0","versions":[{"version","sha256","size","published_at","changelog"}]}]}`, `versions` sorted by semver ascending, `latest` = highest non-prerelease.
   - `GET /v1/packs/{key}/{version}/download` (read token) -> `application/gzip`, header `X-Pack-SHA256`.
   - `PUT /v1/packs/{key}/{version}` (publish token), body = tarball, required header `X-Pack-SHA256` (must match the body), optional header `X-Pack-Changelog` (URL-encoded, max 8 KiB) -> 201 created, 200 identical re-publish, 409 `version_exists` if same version with different sha256, 400 `invalid_pack` (tarball layout/`pack.yaml` mismatch), 401/403 bad token, 413 too large.
   - `GET /healthz`, `GET /readyz` (no auth). Errors use `{"error":{"code","message"}}`.
   - Tarball layout: single top-level directory `<key>/` containing `pack.yaml` (whose `key` and `version` must equal the URL), `daab/`, `laam/`.
3. DAAB server-level admin endpoints require `isGlobalAdmin` (rejects project-scoped admin keys). LAAM endpoints require session role owner/admin via `adminSession`.
4. Rollback is explicit (choose an installed older version); install of a version lower than the active one is refused unless it is a rollback.
5. The release compose currently has no packs volume or `PACKS_DIR` for `kg-server`; fixing that is part of Task 8.

## Review Focus

- Path traversal / symlink / zip-bomb tarballs on every extraction path (registry validation and both clients).
- Same version re-published or re-installed with different content; installing while a run uses the pack; two concurrent installs of the same pack (lock).
- Install interrupted (network drop, bad checksum, disk full): active version untouched, staging cleaned.
- Reload with a broken pack set keeps the old registry and reports the error; enabled-in-project pack missing after reload is reported.
- Tokens leaking through logs, error bodies, the UI or the catalog response.
- Registry down: DAAB/LAAM keep running on installed packs and the screens say so in plain words.
- DAAB and LAAM on different versions: LAAM page and the run warning make it visible; "update to match DAAB" installs exactly DAAB's versions.
- Non-admin users cannot see or call install/update/rollback (UI hidden, API 403).

---

## File Structure

**ennam.kg.packs (new repo, built in a scratch dir, never pushed by agents):** `retail/`, `pharmacy/` (from history), `README.md`, `CHANGELOG.md`, `scripts/release.sh`, `scripts/release_test.sh`, `.github/workflows/publish.yml`.

**ennam.kg.go:** `internal/packdist/` (`manifest.go`, `tarball.go`, `store.go` (+`fsstore.go`), `client.go`, `install.go`, tests), `cmd/kg-pack-registry/main.go`, `internal/packregistry/` (HTTP handlers + auth), `internal/intel/registry_holder.go`, `internal/handler/intel_packs_admin.go`, modifications to `cmd/kg-server/intel_wiring.go`, `cmd/kg-server/main.go`, `internal/intel/engine/{runner,query}.go`, `internal/intel/filedata/canonical.go`, `internal/handler/intel_packs.go`, `cmd/kg-packs/main.go`, `deploy/docker/Dockerfile`, `Makefile`.

**ennam.kg.next:** `src/app/(dashboard)/admin/templates/page.tsx`, `src/hooks/use-template-library.ts`, `src/types/template-library.ts`, `src/components/layout/Sidebar.tsx`, `src/app/(dashboard)/projects/[id]/packs/page.tsx` (version/update badge).

**LAAM:** `src/lib/intel/pack/dist/{manifest.ts,tarball.ts,client.ts,install.ts}` (+tests), `src/app/api/intel/admin/packs/{route.ts,install/route.ts,rollback/route.ts}`, `src/app/(app)/settings/industry-templates/page.tsx`, `src/components/intel/admin/Templates*.tsx`, `src/i18n/dictionaries/intelAdminPacks.ts`, `src/components/settings/SettingsMenu.tsx`, `src/lib/intel/brief/service.ts` (cache rule).

**Workspace:** `docker-compose.yml`, `docker-compose.release.yml`, `LAAM/docker-compose.yml`, `scripts/repos.txt`, `.gitignore`, test pack-path references (list in Task 8), runbooks.

---

### Task 1: ennam.kg.packs repository (local build only)

**Files:** a scratch working copy outside the workspace repo (e.g. `/private/tmp/claude-501/.../scratchpad/ennam.kg.packs`); nothing in the workspace repo is changed except a short README note about where the new repo lives (Task 8 does the removal).

**Interfaces:** Produces `scripts/release.sh` which, given a pack key, builds `dist/<key>-<version>.tar.gz` (layout per Decision 2) and `dist/<key>-<version>.sha256`; the workflow `publish.yml` uploads every changed pack with `PUT ${PACKS_REGISTRY_URL}/v1/packs/{key}/{version}` using `secrets.PACKS_PUBLISH_TOKEN`.

- [ ] **Step 1:** Clone the workspace root repo into the scratch dir (`git clone --no-local <workspace> ennam.kg.packs`) and run `git filter-repo --path packs/ --path-rename packs/:` so the repo root becomes the content of `packs/`; then remove `_projects/` from the working tree with a normal commit `chore: move per-customer mappings out of the shared packs repo` (history of `_projects/` stays in history; that is acceptable, note it in the report). Verify `git log --oneline | wc -l` is about 12-13 and that `retail/pack.yaml` and `pharmacy/pack.yaml` exist at the root.
- [ ] **Step 2:** Bump both `pack.yaml` versions to `0.2.0` (retail first; pharmacy `extends: [retail]` unchanged), add `CHANGELOG.md` (en, Keep a Changelog style: 0.2.0 lists RET-INV-003 v2 store-level stockout metric `retail.stockout_sku_count`, PH-MARGIN-001 v2 severity by margin points, retail roles chain_wide for executive/analyst; 0.1.0 initial), update `README.md` (what a pack is, layout, how to release, version rules: bump `pack.yaml` version on any change to metrics/evidence/rules; semver meaning for packs: MAJOR = removes/renames a metric, entity or rule id; MINOR = adds; PATCH = threshold/wording fixes).
- [ ] **Step 3 (test first):** write `scripts/release_test.sh` (plain bash, `set -euo pipefail`, no external test framework): builds both packs into a temp dist, asserts the tarball has exactly one top-level directory equal to the key, contains `pack.yaml`, no absolute paths or `..`, the `.sha256` file matches `shasum -a 256`, and that releasing with a version that does not match `pack.yaml` fails. Run it: expected FAIL (script missing).
- [ ] **Step 4:** implement `scripts/release.sh <key> [outdir]` (reads version from `pack.yaml` with a tiny awk/sed parse; `tar --no-xattrs --no-mac-metadata` where available so macOS metadata files like `._*` are not included; deterministic ordering via `tar` flags or `LC_ALL=C` sort where possible). Run the test: PASS.
- [ ] **Step 5:** write `.github/workflows/publish.yml`: on push of tags `v*`, checkout, run `scripts/release_test.sh`, build every pack, and for each pack `curl --fail -X PUT` to `${{ secrets.PACKS_REGISTRY_URL }}/v1/packs/$KEY/$VERSION` with headers `Authorization: Bearer ${{ secrets.PACKS_PUBLISH_TOKEN }}`, `X-Pack-SHA256`, `X-Pack-Changelog` (the section of `CHANGELOG.md` for the tag, URL-encoded, trimmed to 8 KiB); treat HTTP 200 (identical) as success and 409 as failure with a clear message. Add `workflow_dispatch`. Style after `ennam.kg.go/.github/workflows/*.yml` (checkout@v5 etc.). Do not create secrets.
- [ ] **Step 6:** commit in the scratch repo (`feat: initial release 0.2.0 with release tooling`, trailer). Do NOT add a remote and do NOT push. Report the scratch path.

### Task 2: Go library `internal/packdist`

**Files:** Create `ennam.kg.go/internal/packdist/{manifest.go,tarball.go,store.go,fsstore.go,client.go,install.go}` and `*_test.go` for each.

**Interfaces (exact):**
```go
// manifest.go
type PackInfo struct {
    Key, DisplayName string
    Version          string
    Extends          []string
}
type VersionInfo struct {
    Version     string    `json:"version"`
    SHA256      string    `json:"sha256"`
    Size        int64     `json:"size"`
    PublishedAt time.Time `json:"published_at"`
    Changelog   string    `json:"changelog"`
}
type CatalogPack struct {
    Key         string        `json:"key"`
    DisplayName string        `json:"display_name"`
    Extends     []string      `json:"extends"`
    Latest      string        `json:"latest"`
    Versions    []VersionInfo `json:"versions"`
}
type Catalog struct{ Packs []CatalogPack `json:"packs"` }
func CompareVersions(a, b string) int            // semver compare, prerelease < release; error-free (invalid sorts lowest)
func ParsePackYAML(r io.Reader) (PackInfo, error)

// tarball.go
const MaxCompressed = 20 << 20; MaxExtracted = 100 << 20; MaxFiles = 2000
type Limits struct{ Compressed, Extracted int64; Files int }
func ValidateTarball(r io.Reader, wantKey, wantVersion string, lim Limits) (PackInfo, sha string, size int64, err error) // reads fully into memory-bounded temp, checks layout + limits + pack.yaml key/version
func ExtractTarball(src io.Reader, dstDir string, wantKey string, lim Limits) error // safe extraction into an empty dstDir
func BuildTarball(srcDir, key string, w io.Writer) (sha string, size int64, err error) // used by tests and tools

// store.go (registry-side storage)
type Store interface {
    Put(ctx context.Context, key, version string, body io.Reader, vi VersionInfo, info PackInfo) (created bool, err error)
    Open(ctx context.Context, key, version string) (io.ReadCloser, VersionInfo, error)
    Catalog(ctx context.Context) (Catalog, error)
}
var ErrVersionExists, ErrNotFound error
// fsstore.go: type FSStore struct{ Dir string }; func NewFSStore(dir string) (*FSStore, error)

// client.go
type Source interface {
    Catalog(ctx context.Context) (Catalog, error)
    Download(ctx context.Context, key, version string) (io.ReadCloser, VersionInfo, error)
}
func NewHTTPSource(baseURL, token string, hc *http.Client) (*HTTPSource, error) // baseURL must be http(s); token optional; never logs token

// install.go
type Installer struct{ Dir string }  // Dir = PACKS_DIR
type Installed struct{ Key, Version string; Active bool }
func (in *Installer) Active(key string) (version string, ok bool, err error)
func (in *Installer) List() ([]Installed, error)                       // active + everything under _versions
func (in *Installer) Install(ctx context.Context, src Source, key, version string) (InstallResult, error)
func (in *Installer) Rollback(key, version string) (InstallResult, error) // version must already be under _versions
type InstallResult struct{ Key, From, To string; Changed bool }
```
Behavior of `Install`: take a per-directory lock (file lock in `PACKS_DIR/_staging/.lock`; if the platform lock is unavailable fall back to an in-process mutex and say so in a comment); if `key` is already active at `version` return `Changed:false`; refuse a lower version than the active one with `ErrDowngrade` (rollback only through `Rollback`); download to `_staging`, verify sha256 against the catalog and the `X-Pack-SHA256`, validate and extract into `_staging/<key>-<version>`, verify the extracted `pack.yaml` equals key/version, move to `_versions/<key>/<version>` (if that exact version already exists with a different content hash recorded in a `.sha256` file next to it -> `ErrImmutable`), then swap: rename active `<key>` into `_versions/<key>/<oldversion>` (if not already there) and rename the new one into `<key>`; clean staging; on any failure restore the previous active directory and clean staging. `Rollback` performs the same swap from `_versions`.

- [ ] **Step 1:** Write tests first (table-driven, `t.TempDir()`, an `httptest.Server` for `HTTPSource`; a fake `Source` for installer tests): CompareVersions cases (0.9.0<0.10.0, 1.0.0-rc.1<1.0.0); tarball validation rejects `../x`, absolute paths, symlink, hardlink, a second top-level dir, missing `pack.yaml`, `pack.yaml` key/version mismatch, oversize (use small `Limits`), too many files, and a gzip bomb (small compressed, large extracted); extraction produces exactly the expected files with sane modes; FSStore: Put twice same sha -> created false, different sha -> ErrVersionExists, Catalog ordering and `Latest`, concurrent Puts of the same version (run with `-race`); HTTPSource sends `Authorization: Bearer`, maps 401/403/404/5xx to typed errors, never includes the token in error text; Installer: fresh install, update (previous goes to `_versions`), idempotent re-install, downgrade refused, rollback works, checksum mismatch leaves the active version untouched, interrupted download leaves no staging directory, two goroutines installing the same pack serialize, immutable-version violation. Run: all FAIL (package missing).
- [ ] **Step 2:** Implement until green. Keep each file under ~300 lines. Use `archive/tar`, `compress/gzip`, `crypto/sha256`, `crypto/subtle` where relevant, `golang.org/x/mod/semver` only if already in `go.mod` (otherwise implement `CompareVersions` by hand; do not add dependencies without noting it).
- [ ] **Step 3:** `cd ennam.kg.go && go test -race -count=1 ./internal/packdist/... && go vet ./... && gofmt -l internal/packdist` clean.
- [ ] **Step 4:** Commit in `ennam.kg.go`: `feat(packdist): versioned pack tarballs, registry store, HTTP source and safe installer`.

### Task 3: `kg-pack-registry` service

**Files:** Create `ennam.kg.go/cmd/kg-pack-registry/main.go`, `ennam.kg.go/internal/packregistry/{server.go,auth.go,server_test.go}`; modify `deploy/docker/Dockerfile`, `Makefile`; workspace `docker-compose.yml`, `docker-compose.release.yml`.

**Interfaces:** Consumes `packdist.Store`, `packdist.FSStore`, `packdist.ValidateTarball`. Implements the registry API contract from Decisions (exact). `packregistry.New(store packdist.Store, readToken, publishToken string, logger *slog.Logger) http.Handler`. Auth: read endpoints accept the read token **or** the publish token; `PUT` accepts only the publish token; empty configured tokens mean the service refuses to start (`main` exits non-zero with a clear message naming the missing variable, never printing token values). Compare with `subtle.ConstantTimeCompare` (model: `requireBearerV2` in `internal/bridge/middleware_auth.go`).

- [ ] **Step 1:** Write `server_test.go` first with `httptest`: catalog empty; publish a real tarball (built with `packdist.BuildTarball` from a temp pack dir) -> 201 then catalog lists it with correct sha/size/changelog; publish identical -> 200; publish same version different content -> 409 `version_exists`; wrong `X-Pack-SHA256` -> 400; tarball whose `pack.yaml` version differs from the URL -> 400 `invalid_pack`; oversize body -> 413; read token cannot PUT (403); no/invalid token -> 401; download returns the bytes and `X-Pack-SHA256`; unknown key/version -> 404; `/healthz` and `/readyz` unauthenticated; the response bodies and logs never contain the tokens (capture slog output). Run: FAIL.
- [ ] **Step 2:** Implement server and `main.go`: env `KG_PACKS_STORAGE_DIR` (required), `KG_PACKS_READ_TOKEN`, `KG_PACKS_PUBLISH_TOKEN` (required), `KG_PACKS_PORT` (default 8090), `--version` flag with ldflags like the other binaries, slog setup, graceful shutdown (copy the `signal.NotifyContext` + `srv.Shutdown` pattern from `internal/bridge/serve.go`), request size cap with `http.MaxBytesReader` (20 MiB + small overhead), read/write timeouts.
- [ ] **Step 3:** Dockerfile: add `go build ... -o /bin/kg-pack-registry ./cmd/kg-pack-registry/` to the builder stage and `COPY` it into `production` (same pattern as `kg-bridge`; the image stays one image with entrypoint override); also build and copy `kg-packs` (currently missing from the image) so operators can run `fetch`/`rollback` inside the container. Makefile: add `kg-pack-registry` to the `build` target.
- [ ] **Step 4:** compose (dev `docker-compose.yml` and `docker-compose.release.yml`): add service `kg-pack-registry` following the `kg-bridge` block exactly (build context/target/entrypoint override `["/app/kg-pack-registry"]`, container_name `daab-packs`, network `ennam-kg`, port `${KG_PACKS_PORT:-8090}:8090`, a named volume `packs_registry` mounted at `/data/packs`, `KG_PACKS_STORAGE_DIR: /data/packs`, tokens as `${KG_PACKS_READ_TOKEN:-}` / `${KG_PACKS_PUBLISH_TOKEN:-}` from the environment so no secret is written to the file, healthcheck copied from `kg-server` style but against `/healthz` on 8090). In the release file use `image: ${KG_IMAGE_PREFIX:-}daab-server:${KG_RELEASE_TAG:-v2.5.0}`. Validate YAML with `docker compose config` ONLY IF docker is available without side effects (`config` does not start anything); otherwise use a YAML parser and say so.
- [ ] **Step 5:** `go test -race -count=1 ./internal/packregistry/... ./internal/packdist/...`, `go vet ./...`, gofmt on touched files, `go build ./...`. Run the binary locally on a scratch dir and port (e.g. 8097) with throwaway tokens exported only in the command's own environment: publish a tarball with `curl`, fetch the catalog, stop it, delete scratch files.
- [ ] **Step 6:** Commit in `ennam.kg.go` (`feat(packregistry): kg-pack-registry service and image/Makefile wiring`) and in the workspace repo (`feat(compose): kg-pack-registry service`; explicit `git add docker-compose.yml docker-compose.release.yml`).

### Task 4: DAAB `RegistryHolder`, reload and server-level library endpoints

**Files:** Create `ennam.kg.go/internal/intel/registry_holder.go` (+test), `ennam.kg.go/internal/handler/intel_packs_admin.go` (+test); modify `internal/intel/engine/runner.go` (`NewRunner`), `internal/intel/engine/query.go` (`NewQueryService`), `internal/intel/filedata/canonical.go` (`NewRegistryCanonical`), `internal/handler/intel_packs.go` (`NewIntelPacksHandler`), `internal/intel/admin/packs.go` callers, `cmd/kg-server/intel_wiring.go`, `cmd/kg-server/main.go`, and the 5 test files that call those constructors (`engine/query_test.go`, `engine/fixture_test.go`, `filedata/canonical_test.go`, `filedata/parity_validation_test.go`, `handler/intel_packs_test.go`).

**Interfaces (exact):**
```go
// internal/intel/registry_holder.go
type RegistryHolder struct{ /* atomic.Pointer[Registry]; mu sync.Mutex; dir string */ }
func NewRegistryHolder(dir string) *RegistryHolder          // loads nothing
func (h *RegistryHolder) Get() *Registry                    // may be nil if never loaded
func (h *RegistryHolder) Reload() (ReloadResult, error)     // LoadRegistry(dir); on error keep old, return error with file:line
type ReloadResult struct{ Added, Removed []string; Changed []VersionChange; Total int }
type VersionChange struct{ Key, From, To string }
// constructors take `func() *intel.Registry` (holder.Get) so tests stay simple
```
Callers read `get()` once into a local per operation (`canonical.go` currently reads twice; `admin.SetPackEnabled` reads `reg.Packs` twice). Startup: a failed first load must no longer disable the whole stack: build the holder, log the error, keep handlers answering 503 `packs_unavailable` while `Get()==nil`, and allow a later `Reload()` or install to bring it up (this adds nil checks in the runner/query paths: when the registry is nil they return the same "packs unavailable" error they return today when handlers are nil; keep that behavior and cover it with tests).

HTTP (all `isGlobalAdmin`, else 403 `forbidden`; JSON `{"error":{"code","message"}}` on errors):
- `GET /api/v1/admin/packs/library` -> `{"source_configured":bool,"source_error":"...?","installed":[{"key","display_name","active_version","versions":["0.1.0","0.2.0"],"enabled_in_projects":N}],"available":[{"key","display_name","latest","versions":[VersionInfo...],"installed_version":"?","update_available":bool}],"drift":[{"key","installed_version_in_projects":"...","disk_version":"..."}]}` (`source_*` fields let the UI say "can't reach the template source" without failing the page; `enabled_in_projects` counts rows from `ListInstalls`/`ProjectsWithEnabledPacks`).
- `POST /api/v1/admin/packs/{key}/install` body `{"version":"0.2.0"}` -> installs via `packdist.Installer` + `HTTPSource(PACKS_SOURCE, PACKS_TOKEN)`, then `holder.Reload()`; returns `{"result":InstallResult,"reload":ReloadResult}`; 409 `downgrade`/`immutable`, 422 `reload_failed` (previous version restored on reload failure), 502 `source_unreachable`, 404 `version_not_found`.
- `POST /api/v1/admin/packs/{key}/rollback` body `{"version":"0.1.0"}` -> `Installer.Rollback` + reload.
- `POST /api/v1/admin/packs/reload` -> `holder.Reload()` result or 422 with the load error; response also lists projects that have an enabled pack that is no longer on disk (`missing_for_projects`).
- Audit: slog `intel packs: installed|rolled_back|reloaded` with acting user id (never tokens).

- [ ] **Step 1:** Write failing tests: holder (good dir -> loaded; then break one pack -> `Reload` errors, `Get()` still returns the previous registry; a `-race` test with goroutines calling `Get().Effective(...)` while another loops `Reload`; a run that already took a catalog snapshot is unaffected by a reload); handlers (403 for non-global-admin incl. a project-scoped admin key; library with a fake source; install happy path using an `httptest` registry plus real tarballs; downgrade 409; checksum mismatch leaves state intact; reload failure after install restores the previous version and returns 422; source unreachable -> library still 200 with `source_error`, install 502). Run: FAIL.
- [ ] **Step 2:** Implement the holder, change the constructors to take the getter, update the 5 test files mechanically, wire everything in `intel_wiring.go`/`main.go` (env `PACKS_DIR`, `PACKS_SOURCE`, `PACKS_TOKEN`; when `PACKS_SOURCE` is empty the library reports `source_configured:false`), add the handlers, register routes next to the existing pack handler.
- [ ] **Step 3:** `go build ./... && go vet ./... && go test -race -count=1 ./internal/intel/... ./internal/handler/... ./cmd/...` (DB-backed tests via `KG_TEST_DATABASE_URL` on :5433 only; state whether any skipped).
- [ ] **Step 4:** Commit in `ennam.kg.go`: `feat(intel): runtime pack reload and server-level pack library endpoints`.

### Task 5: `kg-packs` CLI commands

**Files:** Modify `ennam.kg.go/cmd/kg-packs/main.go` (+ `main_test.go`).

**Interfaces:** new subcommands (the existing `install` keeps its meaning "enable for a project"): `kg-packs versions [--packs-dir D]` (lists active and stored versions per pack), `kg-packs fetch --pack KEY --version V [--source URL] [--token-env NAME] [--packs-dir D]` (installs via `packdist.Installer`; defaults `--source` from `PACKS_SOURCE` and the token from env `PACKS_TOKEN`; the token is never accepted as a flag value), `kg-packs rollback --pack KEY --version V [--packs-dir D]`. Output is plain text; exit code non-zero on failure.

- [ ] **Step 1:** Tests first using an `httptest` registry and temp dirs: `fetch` installs and prints From/To, `versions` lists, `rollback` restores, `fetch` with a missing token env against an authenticated registry fails with a clear message that does not print the token, unknown subcommand usage text mentions the new commands. FAIL.
- [ ] **Step 2:** Implement, `go test -count=1 ./cmd/kg-packs/...`, vet, gofmt on touched files.
- [ ] **Step 3:** Commit in `ennam.kg.go`: `feat(kg-packs): fetch, versions and rollback commands`.

### Task 6: DAAB dashboard — "Template Library" page

**Files:** Create `ennam.kg.next/src/app/(dashboard)/admin/templates/page.tsx`, `src/hooks/use-template-library.ts`, `src/types/template-library.ts`; modify `src/components/layout/Sidebar.tsx` (ADMIN section: `{ href: '/admin/templates', label: 'Template Library', icon: Layers }`) and `src/app/(dashboard)/projects/[id]/packs/page.tsx` (show the active version next to each template and a small "Update available" badge when the library says so; badge links to the library only for global admins).

**Interfaces:** consumes the Task 4 endpoints through the existing `/api/kg/admin/packs/...` proxy (no proxy change needed). The `admin/layout.tsx` already redirects non-admins.

Page behavior (plain words): title "Template library"; subtitle "Install and update the industry templates this server can use."; one card per template: name, "Version in use: 0.2.0", status line ("Up to date" / "New version 0.3.0 available" / "Not installed"), "{n} projects use this", buttons **Install**, **Update**, **See what's new** (changelog text of the target version in a dialog), and an overflow menu **Go back to an earlier version** (select among installed versions, confirm). Update/rollback open a ConfirmDialog: "Update {name} to {version}? Alerts and numbers for the {n} projects that use it may change. You can go back to the earlier version." While running show progress text ("Downloading…", "Checking…", "Applying…" can be a single busy state), then a plain success or error message. Errors mapped to plain words: `source_unreachable` -> "We can't reach the template source right now. Installed templates keep working. Try again later."; `downgrade` -> "That is an older version. Use 'Go back to an earlier version' instead."; `reload_failed` -> "The new version didn't load, so we kept the old one. Details: {message}"; `forbidden` -> "Only server administrators can change templates."; anything else -> generic retry message. When `source_configured` is false show: "No template source is set up on this server yet. Ask your administrator." (no install buttons). Loading skeleton and empty state included.

- [ ] **Step 1:** Types and hooks (`useTemplateLibrary`, `useInstallTemplate`, `useRollbackTemplate`, `useReloadTemplates`; error class carrying the Go `error.code`, copying `use-project-packs.ts`).
- [ ] **Step 2:** Page + sidebar entry + project-tab badge per the behavior above.
- [ ] **Step 3:** `npm run lint` on touched files and `npm run build`; both pass (27 pre-existing lint errors elsewhere are known). Render the page against a mocked fetch (temporary dev server on an unused port, Playwright) at 1440 and 375, view the screenshots, check every state (loading, no source, up to date, update available, error), then remove the temp server and files. State honestly which states were visually verified.
- [ ] **Step 4:** Commit in `ennam.kg.next`: `feat(admin): Template Library page to install, update and roll back templates`.

### Task 7: LAAM — install/update client, API and "Industry templates" settings page

**Files:** Create `LAAM/src/lib/intel/pack/dist/{manifest.ts,tarball.ts,client.ts,install.ts}` + tests; `LAAM/src/app/api/intel/admin/packs/route.ts` (GET status), `.../packs/install/route.ts` (POST), `.../packs/rollback/route.ts` (POST) + tests; `LAAM/src/app/(app)/settings/industry-templates/page.tsx`; components `LAAM/src/components/intel/admin/Templates*.tsx` + tests; `LAAM/src/i18n/dictionaries/intelAdminPacks.ts` + test; modify `LAAM/src/components/settings/SettingsMenu.tsx` (+test: admin-only row "Industry templates"), `LAAM/src/lib/intel/brief/service.ts` (pack cache rule below).

**Interfaces:** TypeScript mirror of `packdist` (same on-disk layout, same limits, same checks): `readCatalog(source)`, `installPack({dir, source, key, version})`, `rollbackPack({dir,key,version})`, `listInstalled(dir)`. Tar handling: use the `tar` npm package if it is already in the dependency tree (check `npm ls tar`); otherwise implement a minimal USTAR reader (about 100 lines) rather than adding a new top-level dependency, and state the choice. Env: `PACKS_DIR` (existing via `packsDir()`), `PACKS_SOURCE`, `PACKS_TOKEN`. The registry URL is operator-configured: do NOT run it through the MCP SSRF guard (`assertSafeUrl` would reject a docker-network address); do require `http(s)` scheme and never accept a URL from a request body.

`GET /api/intel/admin/packs` -> `{ sourceConfigured, sourceError?, installed:[{key, activeVersion, versions[]}], available:[{key,latest,versions[],updateAvailable}], daab?: {packs:[{key,version}]}, mismatch:[{key, daabVersion, laamVersion}] }`; the DAAB versions come from the existing provider `listMetrics().packs` for the owner's business projects (try/catch; absent when DAAB is unreachable); `mismatch` also reads the latest `analysis_run.summary.warnings` entries starting with `pack_version_mismatch:` as a fallback. `POST install` body `{key, version}` and `POST rollback` body `{key, version}`, plus a convenience `POST install` body `{matchDaab:true}` that installs exactly the versions DAAB reports for every pack where LAAM differs. Guard: `adminSession(true)` (owner/admin), `readJson`, zod `strictObject`, `audit_log` row per write (`intel.packs.install`, `intel.packs.rollback`). Error codes (HTTP): `source_not_configured` (409), `source_unreachable` (502), `version_not_found` (404), `downgrade` (409), `immutable` (409), `bad_pack` (422), `forbidden` (403).

Pack cache rule: `brief/service.ts` caches loaded packs per `packVersion` string for the process lifetime. Installing a **new** version changes the key, so nothing is stale; because versions are immutable and the installer refuses a changed re-install, in-place overwrite cannot happen. Add a test that documents this and, when `installPack` succeeds, call an exported `clearPackCache()` anyway (cheap and safe).

UI (plain language, vi/en/zh): Settings row "Industry templates" ("Which industry rules LAAM uses, and keeping them up to date"). Page: a table or cards per template: name, "In use: 0.2.0", "DAAB uses: 0.2.0" with a green "Same version" or an amber "Different from DAAB — results may be wrong" badge, "Latest available: 0.3.0"; buttons **Update to latest**, **Match DAAB (0.2.0)** (only when different), overflow **Go back to an earlier version**; confirm dialogs in plain words; the "source not set up" and "can't reach source" states; success and error messages from the error codes above. The Home data-status area is not changed in this task.

- [ ] **Step 1:** Dictionary + test first (all three languages present; no jargon words `tarball`, `sha256`, `registry`, `PACKS_` in visible English strings; "DAAB" only inside the gloss "your data tool (DAAB)").
- [ ] **Step 2:** Library tests first with temp dirs and an in-process HTTP server: catalog parse; install happy path; checksum mismatch leaves active untouched; path traversal / symlink / oversize / zip bomb tarballs rejected; downgrade refused; rollback; immutable violation; concurrent installs serialize (use a lockfile or an in-process async mutex with a comment on limits); token never present in thrown error messages. FAIL, then implement `dist/*`.
- [ ] **Step 3:** API route tests (harness `src/lib/intel/testing/route-harness.ts`, style of `src/app/api/intel/admin/**/route.test.ts`): 401/403 for non-admin, 400/415, happy paths record `audit_log` inserts, error code mapping, `matchDaab` installs exactly DAAB's versions. Implement routes.
- [ ] **Step 4:** Components and page with tests (Testing Library): states per the UI section, confirm-before-update, errors in plain words, mismatch badge, admin-only menu row.
- [ ] **Step 5:** `cd LAAM && PACKS_DIR=../packs npx vitest run src/lib/intel src/app/api/intel src/components src/app src/i18n` (3 known ConstellationClient failures), `npx tsc --noEmit` (tolerated: `executors.test.ts`), eslint on touched files. Visual check with a temp dev server and mocked fetch like the previous admin UI task (state honestly what was and was not verified; no real DB, no real login).
- [ ] **Step 6:** Commit in `LAAM`: `feat(intel): install, update and roll back industry templates from settings`.

### Task 8: Move references, compose wiring, docs

**Files:** modify `docker-compose.yml`, `docker-compose.release.yml`, `LAAM/docker-compose.yml`, `scripts/repos.txt`, `.gitignore` (workspace); tests that locate packs by relative path; docs.

- [ ] **Step 1 (tests no longer assume a sibling directory):** change `ennam.kg.go/internal/intel/realpacks_test.go:14` and `internal/intel/filedata/parity_pack_harness_test.go:87` to honour `PACKS_DIR` first (fall back to `../../../packs`, then skip with a message naming `PACKS_DIR`); verify `pharmacy_enum_test.go:30` and `packtest/fixture_test.go:29` already honour `PACKS_DIR`. In LAAM change `src/lib/intel/pack/packs-content.test.ts:11`, `src/lib/intel/admin/repo.test.ts:222,463`, `src/app/api/intel/admin/options/route.test.ts:20`, `src/app/api/intel/admin/projects/[id]/scopes/route.test.ts:15` to read `PACKS_DIR` first and fall back to `../packs`. Keep the existing CI behaviour in `packs-content.test.ts` (fails in CI when the directory is missing).
- [ ] **Step 2 (compose):** workspace `docker-compose.yml` and `LAAM/docker-compose.yml`: replace the hard-coded `./packs:/packs:ro` / `../packs:/packs:ro` with `${PACKS_HOST_DIR:-./packs}:/packs` (writable, because installs write there) for `kg-server` and the LAAM `app`, keep `PACKS_DIR: /packs`, and add `PACKS_SOURCE: ${PACKS_SOURCE:-}` and `PACKS_TOKEN: ${PACKS_TOKEN:-}` to both. **`docker-compose.release.yml`: add the missing `PACKS_DIR: /packs`, the `${PACKS_HOST_DIR:-./packs}:/packs` volume and the two env variables to `kg-server`** (currently absent: a release stack starts with no packs). The `kg-pack-registry` block is already added in Task 3. Do not start or restart anything.
- [ ] **Step 3 (repo plumbing):** add `packs` to `scripts/repos.txt` using the `github-dragoon` SSH alias form consistent with how the file is read by `bootstrap.sh` (read the script first; if its URL form cannot express the alias, document the manual clone command instead of changing the script); add `/packs/` to the root `.gitignore` ONLY in the final handoff step (Task 9 note), not now, because the directory is still tracked.
- [ ] **Step 4 (docs, Vietnamese):** new runbook `docs/superpowers/runbooks/2026-10-06-pack-distribution-and-deploy.md`: (a) what changed and the roles (server admin installs/updates, project admin enables); (b) how to release a pack (bump `pack.yaml`, CHANGELOG, tag) and what CI does; (c) how to install on DAAB and LAAM from the UI and from the CLI (`kg-packs fetch ...`); (d) update, rollback, "match DAAB" flows; (e) mapping is separate (`import-mapping`, `run-metrics`) with the order pack -> mapping -> metrics; (f) env variables table; (g) **a section "Yêu cầu hạ tầng cho DevOps"**: a dedicated URL for the registry (e.g. `packs.daab.ennam.vn`, HTTPS), storage (volume now, S3 later: the `Store` interface in `internal/packdist/store.go`), two tokens in the secrets module, CI secrets `PACKS_REGISTRY_URL` and `PACKS_PUBLISH_TOKEN`, writable `/packs` volumes for DAAB and LAAM, the release compose fix, questions for DevOps (where does LAAM run, domain/LB management, existing registry/CloudFront). Also update `docs/superpowers/runbooks/2026-10-05-test-and-usage-guide.md` section on packs with a pointer to the new runbook, and `packs/README.md` with a note that the content moved (final move is Task 9).
- [ ] **Step 5:** run the Go and LAAM suites touched by Step 1 (`PACKS_DIR=/Users/.../workspace/packs` explicit and also unset to see the skip path), `go vet`, `tsc`, eslint on touched files, and validate the three compose files parse (`docker compose -f <file> config -q` only if it has no side effects, otherwise a YAML parse).
- [ ] **Step 6:** commits: `ennam.kg.go` (`test(packs): locate packs through PACKS_DIR`), `LAAM` (same message), workspace (`chore(compose): writable packs volume, packs source env and release stack fix`, plus docs).

### Task 9: End-to-end verification (scratch only) and handoff

**Files:** create `docs/superpowers/test-results/2026-10-06-pack-distribution-verification.md`. No source changes except fixes reported back to the controller.

- [ ] **Step 1:** In a scratch dir, build `kg-pack-registry` and `kg-packs` and start the registry locally on a free port with throwaway tokens set only in that process's environment; build both packs from the scratch `ennam.kg.packs` repo (Task 1) with `scripts/release.sh` and publish 0.2.0 of retail and pharmacy with `curl`; check the catalog.
- [ ] **Step 2:** With an empty scratch `PACKS_DIR`, run `kg-packs fetch` for retail then pharmacy; confirm layout, `kg-packs versions`; run `intel.LoadRegistry` against the result via the real-packs test with `PACKS_DIR` pointing at it (the same pack count as before: retail 27 metrics, pharmacy 33). Publish a modified 0.3.0 (e.g. one threshold changed), fetch it, check the previous version is under `_versions`, `rollback`, check content equals 0.2.0. Try the attack tarballs (traversal, symlink, bomb, wrong sha) against both the registry (publish) and the CLI (fetch of a tampered file) and record the outcomes.
- [ ] **Step 3:** Run the real DAAB admin endpoints in-process through the handler tests (no running server needed), and run the LAAM library against the same scratch registry with a small tsx script; compare the on-disk results to the Go installer's.
- [ ] **Step 4:** Write the verification report: commands run, outputs, PASS/FAIL per check, what was NOT verified (real browser UI against real backend, S3 storage, production compose, CI workflow on GitHub). Clean up all scratch processes and directories.
- [ ] **Step 5 (handoff list for the user, not executed by agents):** (1) review and approve pushing the scratch `ennam.kg.packs` repo to `git@github-dragoon:En-Nam/ennam.kg.packs.git`; (2) then remove `packs/` from the workspace repo (`git rm -r packs` except `_projects/`, move `_projects/` to `docs/demo/` or similar) and add `/packs/` to `.gitignore`; (3) set the compose env `PACKS_HOST_DIR` and the tokens on the servers; (4) hand the DevOps section to DevOps; (5) rebuild the images for DAAB and LAAM and recreate the containers (user-run).

---

## Self-Review

- **Spec coverage:** own repo with history and versions (T1); registry service + deploy conventions (T3); safe versioned install, rollback, reload (T2, T4, T5); admin UIs for DAAB and LAAM with update button (T6, T7); LAAM/DAAB mismatch visibility (T7); release-compose bug and writable volumes (T8); DevOps handoff (T8 docs, T9); mapping stays separate (documented T8; separate plan later).
- **Placeholders:** none; unresolved choices are bounded (tar library vs minimal reader in T7; URL form in `repos.txt` in T8) with a stated fallback.
- **Type consistency:** `PackInfo`, `VersionInfo`, `Catalog`, `Installer`, `InstallResult`, `RegistryHolder`, `ReloadResult` are defined once (T2/T4) and the HTTP shapes in T4 (library/install/rollback/reload), T6 and T7 use the same field names (`key`, `latest`, `versions`, `update_available` on the Go side, camelCase on the LAAM side by design); env names fixed in Global Constraints.
- **Review Focus coverage:** traversal/bombs (T2, T3, T7 tests), immutability and concurrency (T2, T7), failed install keeps previous (T2, T4), reload failure (T4), token leakage tests (T2, T3, T5), registry-down behaviour (T4, T6, T7), mismatch (T7), non-admin (T4, T6, T7).

---

## Shared install protocol (added after the Task 2 review; binding for Go `packdist` and the LAAM TypeScript installer)

DAAB and LAAM may share one `PACKS_DIR` (dev stack bind mount) or use separate ones; the installers must be safe in both cases, so the protocol works across runtimes.

- **Lock:** `PACKS_DIR/_staging/.lockdir` created with `mkdir` (EEXIST = held; atomic on every OS). Inside it `owner.json` = `{"pid":N,"host":"<hostname>","runtime":"go|node","startedAt":"<ISO-8601>"}`. Acquire = loop `mkdir` with ~200 ms polling that honours the caller's context/abort; give up with a typed "busy" error after the caller's timeout (default 60 s). A held lock is **stale** when `owner.json` says the same host and the pid is not alive, or `startedAt` is older than 15 minutes; a stale lock is taken over by renaming it to `.lockdir.stale-<random>` and removing that. Release = remove `owner.json`, then `rmdir`. Cleaning `_staging` is allowed **only while holding the lock** (so it can never delete another installer's work).
- **Swap journal:** before the first rename of an install/rollback, write and fsync `PACKS_DIR/_staging/swap.json` = `{"key","current","parked","stale","createdAt"}` where `parked` is a path **outside** the directories cleaned at lock time (e.g. `_versions/<key>/.prev-<current>`). On acquiring the lock, before cleaning `_staging`, validate `swap.json` (relative slash paths, exactly `_versions/<key>/.prev-<current>` and `_versions/<key>/.stale-<v>`; anything else is refused and the file is kept). Then: if `parked` exists and `<key>/` is missing, rename `parked` back to `<key>/` (on failure keep the journal and report it); if `parked` exists and `<key>/` exists, rename `parked` to `_versions/<key>/<current>/` (delete it if that directory already exists); if `stale` exists, delete it when `<v>` is now active or `_versions/<key>/<v>/` exists, otherwise rename it back to `_versions/<key>/<v>/`; fsync PACKS_DIR and `_versions/<key>/`, then delete the journal. Absolute paths in the journal are refused by both runtimes. Both runtimes implement this recovery. fsync the parent directories after the renames.
- **Reload under the lock:** the Go installer exposes `(*Installer).WithLock(ctx, func() error) error`; DAAB reloads its registry inside that callback after Install/Rollback so a load can never see a half-swapped pack.

**Journal and directory naming conventions (fixed by the Go implementation, commit 88b05ce; LAAM follows):** paths inside `swap.json` are relative to `PACKS_DIR` and use `/` separators (an absolute or escaping path is refused and the journal kept); the parked previous version is `_versions/<key>/.prev-<current>`; the set-aside stale copy is `_versions/<key>/.stale-<version>`; recovery follows the rules in the Swap journal item above. On other hosts or Windows a crashed holder's lock is taken over only after the 15-minute stale age (pid cannot be checked).

**Takeover (fix round 2; both runtimes must implement exactly this):**
1. A waiter that finds `.lockdir` held reads `owner.json` and decides whether the lock is stale, using the rules above. If it is not stale, the waiter keeps polling.
2. If it is stale, the waiter claims the takeover by creating `PACKS_DIR/_staging/.lockdir.takeover` with `mkdir`. Only one waiter can hold the claim at a time.
   - If the claim already exists and is older than **30 s** (by the claim directory's mtime), it was left by a crashed waiter. Remove it with `rmdir` and keep polling.
   - If the claim is younger than 30 s, another waiter is taking over. Keep polling and re-evaluate.
3. While holding the claim, the waiter re-reads `owner.json` and takes over **only if** it is still the same stale owner: same `pid`, `host` and `startedAt`, and the same `.lockdir` mtime. Otherwise it releases the claim and keeps polling.
4. If it is the same stale owner, the waiter:
   1. renames `.lockdir` to `.lockdir.stale-<random>` and removes that directory;
   2. takes the normal lock with `mkdir .lockdir` and writes its own `owner.json`;
   3. only then removes the claim with `rmdir`.
   If that `mkdir` fails with EEXIST, a plain waiter won the freed lock; that is fine. Release the claim and keep polling.
5. A lock is never renamed back.
6. Cleaning `_staging` while holding the lock skips `.lockdir` and `.lockdir.takeover`.

**Journal `createdAt`:** informational only. An empty or missing value is accepted and recovery proceeds normally. A non-empty value that is not RFC 3339 is refused. Go writes RFC 3339 with nanoseconds in UTC.

**File modes (DAAB and LAAM may run as different uids):** these modes are set regardless of the umask:
- `.sha256` records: 0644.
- Extracted pack files: 0644. Extracted pack directories: 0755.
- Newly created `_versions/` and `_versions/<key>/` directories: 0755. Directories that already exist are not changed.

**Final-review alignment (both runtimes):**
- **Unreadable `startedAt`.** If `owner.json` has a `startedAt` that is missing or cannot be parsed, the lock is stale immediately.
- **Lock left by our own pid.** A lock on our host that names our own pid but was taken before this process started is stale. This happens when a container restarts with the same hostname and PID 1.
- **Write `owner.json` before releasing the claim.** After a takeover, the new `owner.json` is written inside the fresh `.lockdir` before the takeover claim is removed.
- **Checksum record before the swap.** The `.sha256` record is written before the swap.
- **Required download header.** A download without a valid `X-Pack-SHA256` header is refused.
- **No symlinks.** If `_versions` or `_versions/<key>` is a symlink, the installer refuses with a needs-repair error.

