# DAAB — Ennam Knowledge Graph Platform · Release v1.0.0

**Date:** 2026-06-24
**Source commit:** `4dfdda2` (`4dfdda2eaa2006f591925e23d2fa8b7f06673ce6`, `ennam.kg.go` @ `main`)
**Built by:** technical-lead session (local build, verify-first)

## Images

All three carry tags `:4dfdda2` (commit SHA), `:v1.0.0` (semver), and `:latest`.

| Image | Service | Base / stage | Size |
|---|---|---|---|
| `daab-server` | Go API (`kg-server`) | `deploy/docker/Dockerfile` `target: production` — alpine, static `CGO_ENABLED=0` binary, non-root | 38.3 MB |
| `daab-python` | Python indexer **and** worker (one image, command-switched) | `python:3.12-slim`, `uv --no-dev`, non-root | 1.68 GB |
| `daab-dashboard` | Next.js 16 dashboard | `node:20-alpine`, standalone output, non-root | 284 MB |

> Naming note: local self-hosted images are named per service — `daab-server`, `daab-python`, `daab-dashboard` — matching the `daab` stack. (The cloud CI/ECR path uses its own repo names `ennam-kg-staging`/`-production` for the Go image.)

## Pre-release verification (security gate g2a)

The release commit includes the cross-project IDOR fix (`6ceda27`). Before freezing images, the
`recall_isolation` suite was run **with `-race` against a real migrated Postgres**, reproduced in
Linux containers (cgo/gcc unavailable natively on the Windows host):

- **Unit (T1–T7 logic):** 10/10 PASS with `-race`.
- **Integration `TestRecallIsolation_FullChain`:** 4/4 subtests PASS with `-race` — body-override 403,
  `cross_project_ids` 403, by-UUID history 404, **and** the dual-scoped positive control (proves real
  isolation, not blanket-deny).
- `go build ./...` OK, `go vet ./internal/handler` OK.

This is the **first time the integration test has ever executed.** Its seed INSERT was never schema-valid
(missing `properties.context`/`rationale` required by `chk_decision_properties`, migration 000008). A
**fixture-only** fix was applied — assertions unchanged, production isolation code untouched.

## Smoke test (released images)

Brought up via `docker-compose.release.yml`; all healthchecks green; authenticated path verified:

- `kg-server` `/healthz` 200, `/readyz` 200; auto-migrated to schema version 66 (clean).
- `/api/v1/projects` → **401** without auth, **200** with the seeded admin key (returns seeded project).
- `indexer` `/healthz` 200; `dashboard` `/` 307 (login redirect); `worker` running (no healthcheck by design).

## Running the bundle

```bash
cd DAAB
cp .env.release.example .env      # fill required secrets
docker compose -f docker-compose.release.yml up -d
```

## Known limitations / follow-ups (read before production)

1. **No self-hosted production config profile.** `config/environments/{production,staging}.yaml` require
   AWS (Secrets Manager + CloudWatch) and cannot boot standalone. The bundle runs the AWS-free
   `development` profile, hardened via env (info logging, DB-backed auth, explicit secrets). Real AWS
   deploys still go through the existing CI/ECS pipeline (`deploy-staging.yml` / `deploy-production.yml`),
   which builds **only the Go image** and injects `production.yaml`. **Recommended:** add a
   `selfhosted.yaml` profile (no AWS, `auto_migrate: false`, `verbose_errors: false`) for on-prem.
2. **Python & Next.js have no release pipeline.** Only `ennam.kg.go` has CI/CD, an ECR repo, and an ECS
   service. These two images are net-new here and have no upstream registry/deploy automation yet.
3. **g2a not yet green *in CI*.** The fixture fix is **uncommitted**, and CI's `test` job runs without
   `-tags=integration`, so `TestRecallIsolation_FullChain` isn't wired into CI. To satisfy the CTO gate
   literally: commit the fixture fix and add an integration test job (Postgres service + `-tags=integration`).
4. **CI Go version drift.** CI pins Go **1.23**; `go.mod` requires **1.25.7**; image base is **1.26-alpine**.
   The image build is fine; align the CI `GO_VERSION` to avoid a latent break.
5. **Well-known seeded admin key.** Migration `000009_seed_dev_data` seeds the public dev key
   `ennam_kg_dev_0000…` as an **admin**. Fine for local; **rotate/revoke for any real deployment.**
6. **Write-IDOR sweep still open** (`update*`/`deprecate` by-UUID) per the principal's checkpoint — a
   separate hardening track, not part of this read-isolation gate.

## Update — g2a finished; local-Docker solutions for items 2/3/4

**g2a (security gate) — DONE (locally proven; one push away from CI-green).**
Branch `security/finish-g2a-isolation-ci` (commit `2990bb2`) off `4dfdda2`:
- Fixture fix so `TestRecallIsolation_FullChain` is schema-valid (assertions unchanged).
- `ci.yml`: integration gate step (`-tags=integration … -race`), Go 1.23→1.25, golangci-lint→v2.3.0,
  Postgres → `pgvector/pgvector:pg16`, migrations apply `*.up.sql` only with `ON_ERROR_STOP`.
- Reproduced the corrected CI gate in Docker on **go1.25.11**: unit 10/10 + integration 4/4, both `-race`, `ok`.
- Remaining: `git push` the branch → open PR so GitHub Actions runs it green (cannot trigger Actions locally).

**#2 (no pipeline for Python/Next) — SOLVED with local Docker.**
A `registry:2` container (`localhost:5000`) is a full AWS-free registry. All 3 images pushed
(`v1.0.0` + SHA + `latest`), catalog + pull round-trip verified. Reusable: `scripts/release-local.sh`.
The bundle takes `KG_IMAGE_PREFIX` (e.g. `localhost:5000/`) to pull from it.

**#4 (CI Go-version drift) — SOLVED in the same g2a commit** (Go 1.25 + golangci-lint v2.3.0; build
validated in Docker). golangci-lint v2 vs action pin still wants one real CI run to confirm the lint job.

**#3 (no self-hosted production profile) — solution identified; needs a greenlight (re-cuts the release).**
Add `EnvSelfHosted` to `ValidEnvironments` (`internal/config/server.go`) + `config/environments/selfhosted.yaml`
(secrets `provider: env`, CloudWatch off — the metrics publisher already no-ops unknown envs, `auto_migrate: false`,
`format: json`, `level: info`, `verbose_errors:false`, `rate_limiting_enabled:true`). Then run images with
`ENVIRONMENT=selfhosted`. NOTE: this is a Go code change → new commit/SHA → the v1.0.0 image would be rebuilt
off that commit (not `4dfdda2`). Decide: fold into v1.0.0, or ship as v1.0.1.

## Update — self-hosted (no AWS) + local auto-deploy (DONE)

**#3 self-hosted profile — SHIPPED** (commit `059300b`, branch `security/finish-g2a-isolation-ci`):
`EnvSelfHosted` + `config/environments/selfhosted.yaml` — AWS-free, production-like (JSON logs,
`verbose_errors:false`, rate limiting on, no pprof, secrets from env, no CloudWatch/Secrets Manager,
`auto_migrate:true` so a fresh stack is usable). Go image rebuilt; `docker-compose.release.yml` now runs
`ENVIRONMENT=selfhosted`. Smoke-tested: all healthchecks green, `"environment":"selfhosted"` + JSON logs in
the boot line, `/api/v1/projects` 401→200. **No AWS anywhere in the local path.**

**Local auto-deploy — DONE.** Entirely on local Docker, no cloud. Two mechanisms:

**Primary — track `origin/main` (`scripts/watch-main.sh`):** a polling watcher (local GitOps). Every
`WATCH_INTERVAL`s (default 60) it `git fetch`es each sub-repo's `origin/main`; when main advances it
rebuilds that service's image **from `origin/main` via `git archive`** (no checkout — never touches your
working tree) and `docker compose up -d` redeploys only the changed container. This is the "commits land on
main → local Docker updates" trigger. Run `bash scripts/watch-main.sh` (Ctrl+C to stop), background it with
`nohup … >> .watch-main.log 2>&1 &`, or schedule `--once` via Task Scheduler/cron. State in `.deploy-state/`.
- Verified: with state == `origin/main` it's a no-op; with main advanced it builds `daab-server` from main and
  redeploys, `/healthz` 200. Builds from `origin/main` regardless of which branch the working tree is on.

**Opt-in — build-on-commit (`scripts/deploy-local.sh` + `scripts/install-deploy-hooks.sh`):** `post-commit`/
`post-merge` hooks redeploy on **local** commits (fast dev iteration, any branch). **Disabled by default**
now that poll-`main` is the model (the two would otherwise fight over what's deployed); re-enable with
`install-deploy-hooks.sh`. The installer self-heals a stale `core.hooksPath`. `deploy-local.sh
[server|python|dashboard|all]` also works as a manual one-shot redeploy.

> Why no AWS for local: the AWS bits live only in the cloud deploy workflows + the `production`/`staging`
> config profiles. The self-hosted path uses the `selfhosted` profile + the local registry/compose + git-hook
> deploy — zero AWS. The cloud workflows remain untouched for a future cloud deploy.

## Artifacts added this session

- `DAAB/docker-compose.release.yml` — pinned-image release bundle (no build, no bind-mounts, AWS-free profile).
- `DAAB/.env.release.example` — documented required secrets.
- `DAAB/ennam.kg.go/internal/handler/recall_isolation_integration_test.go` — fixture fix (uncommitted).
