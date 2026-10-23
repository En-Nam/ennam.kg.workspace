# LAAM: no automatic provider fallback; single instance for now (owner decision 2026-10-22)

- **No automatic provider fallback.** When the chosen provider fails, chat shows the coded error and the USER switches model. Reason: users must know which provider answers so they can reason about cost. Matches the existing "KHÔNG tự fallback" design in src/app/api/chat/route.ts. Do not add silent or opt-in fallback without a new owner decision.
- **Multi-instance hardening deferred.** Rate limits (in-memory Map), confirm single-flight (in-memory Set + audit_log) and orphan-sweep assume ONE app process. Correct for the current one-container deploy. Revisit only when horizontal scaling is planned: Postgres-backed limiter + nonce lock, lease/heartbeat for workflow runs.
- Context: harness weakness review, doc "LAAM — Agent Harness Overview" (claude.ai artifact); items 1 and 2 there.
