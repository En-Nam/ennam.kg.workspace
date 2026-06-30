# DAAB Consumer-Key + User-Scope (D3 / gate g2b) — Design Spec (2026-06-25)

> **Status:** DRAFT — direction CHỐT; Gate-0 ✓ closed; awaiting user review before plan.
> **Goal:** Hoàn tất gate **g2** để bật consumer (AAAA/LAAM) tiêu thụ `kg_recall`/`kg_remember`: làm `user_id` scoping **live** (g2b) + định nghĩa **consumer-key class** (D3). Memory-of-record P0 đã ship project-scope; phần này thêm tầng **user-scope** an toàn xuyên platform.
> **Implements:** `mem:backlog/cto-directives-2026-06-23` D3 + gate g2b · tiếp nối `mem:decisions/ecosystem-hermes-allocation` (DAAB = keystone owner; AAAA/LAAM = thin consumer).

---

## 0. GATE-0 — ✅ ĐÓNG (2026-06-25)

> `global/ecosystem/shared-memory-contract` **không nằm trong Serena store của repo này** (nó ở store cross-platform của NewEcoSystem orchestrator, không reachable từ đây). Nguồn authoritative **có sẵn local** = `backlog/cto-directives-2026-06-23` (ratified), nó ghi binding requirements của contract và **xác nhận hướng spec**:
> - **D7:** "NO opaque-UUID args — **resolve project_id/user_id from the agent key**" → đúng mô hình **per-user key** (resolve từ key), loại JWT per-call. ✓
> - **D3:** consumer key `role=agent`, non-empty `project_ids`, `allow_project_override=false`, "Required BEFORE issuing AAAA/LAAM keys". ✓ khớp §3.1.
> - **g2b:** `agent_context.user_id` + recall filters → T6/T7. ✓ khớp §3.2/§3.4. (Directive cũng nêu `knowledge_nodes.user_id` — spec này tách ra, xem §2: memory dùng `agent_context`.)
> - **GATE:** "g2 (g2a CI-green AND g2b live) must pass before ANY consumer wires recall." → đây chính là mục tiêu spec.
>
> ⚠️ Còn lại (không chặn): nếu sau này đọc được `global/ecosystem/shared-memory-contract` của orchestrator và thấy khác → revisit. Hiện directive local đã đủ authoritative để tiến hành.

## 1. Bối cảnh & quyết định nền (đã verify bằng code)

**Trạng thái gate (kiểm 2026-06-25):**
- ✅ **g2a** — project isolation + role enforcement: BA-015 Phase A+B xong, `recall_isolation_test` xanh (foreign project_id body→403, cross_project_ids→403, by-id node lạ→404).
- ❌ **g2b** — user_id scoping: **inert hoàn toàn**. Store ĐÃ sẵn field UserID (write `AgentContextParams.UserID` + recall `AgentRecallParams.UserID` + filter `AND a.user_id`, store:15/133/165) **nhưng handler không bao giờ truyền**; `api_keys` **thiếu cột user_id**. → net-new (xem §3.2). (`knowledge_nodes.user_id` chưa có — không cần cho memory, memory dùng `agent_context`.)
- ❌ **D3** — consumer-key class: chưa có.
- ✅ Supabase login: DONE — `/auth/supabase` verify JWKS ES256 → JIT user → mint key `web-session-*`. (Link cũ `users.api_key_id` là slot đơn; spec này thêm forward-column `api_keys.user_id`.)

**AAAA (consumer thật) — bằng chứng từ `other_projects/am-ai-agents`:**
- Prisma schema **không có** `tenant_id`/`org_id` → cô lập theo **`userId`**. Deal = `Project{userId}`. Auth = Supabase. Chạy **server-side** (Inngest, `AiRunLog.userId`). **Chưa** tích hợp DAAB (greenfield).
- ⇒ AAAA-user 1:1 DAAB-user là ranh giới cô lập đúng (multi-tenancy là gate tương lai của AAAA, không phải DAAB).

**Quyết định nền:** identity của consumer chảy vào DAAB qua **per-user key (token-exchange)**, KHÔNG per-call JWT:
```
end-user (Supabase) → consumer backend gọi /auth/supabase (token) → DAAB key user-scoped (cache)
   → dùng key làm Bearer khi gọi kg_remember/kg_recall thay mặt user đó
   → user_id resolve từ cột api_keys.user_id của key (no opaque-UUID args — đúng directive D7)
```
Bearer tĩnh per-MCP-connection KHÔNG phải vấn đề: human-MCP dùng key cá nhân (key có `user_id`); platform-backend là HTTP client động, set Bearer per-user/per-request.

## 1.1 Consumer connection model (authoritative — `decisions/ecosystem-hermes-allocation`)

- **Cả AAAA và LAAM nối DAAB qua MCP** ("thin MCP clients"). AAAA: `kg_recall` qua MCP → inject vào prompt-cached Claude (Inngest). LAAM: `kg_recall`/`kg_search_sessions` qua MCP (Qwen tool-loop, read-only). MCP transport = Streamable HTTP + **Bearer token per-config** (như UI "Thêm máy chủ MCP": URL + token).
- ⇒ **Bearer key = identity.** Per-user memory yêu cầu **key user-scoped làm Bearer**:
  - **(a) thủ công:** end-user paste personal DAAB key (dashboard API-key, gắn user) vào config MCP của họ — giống human-MCP (Q-3).
  - **(b) programmatic:** consumer backend exchange Supabase token → `consumer-session-*` key (§3.3) → set Bearer per-user-session.
- **1 token platform chung** ⇒ chỉ **project/platform-scope** (không per-user) — hợp lệ nhưng không cô lập user.
- ⚠️ **Open (ecosystem Q#3):** MCP-hop latency cho prompt doc-gen của AAAA → có thể cần read-through cache/replica. Ngoài phạm vi spec này (consumer-side concern), ghi nhận.

## 2. Non-goals
- ❌ JWT/user-assertion **per-call** (đã loại — thừa, lệch directive resolve-from-key).
- ❌ `knowledge_nodes.user_id` (node-level user scope) — ngoài phạm vi memory; tách spec riêng nếu cần.
- ❌ AAAA multi-tenancy (`tenant_id`) — việc của AAAA.
- ❌ Retention/confidence/`kg_search_sessions` — spec riêng.
- ❌ Tự động phát hành key cho AAAA/LAAM (issuance vận hành) — spec này định nghĩa **class + policy**, không tạo key thật.

## 3. Phạm vi (4 mảnh)

### 3.1 Consumer-key class + policy
- Phân biệt **consumer key** với internal/human key. Consumer key: `role=agent`, `project_ids` **non-empty**, `allow_project_override=false` (đã có cột `AllowProjectOverride` trong model — verify enforcement).
- Policy phát hành: chặn cấu hình nguy hiểm (admin + empty project_ids cho consumer). Áp **chỉ khi** phát hành consumer key (không phá admin-all hợp lệ — xung đột đã nêu ở `comms/active/daab-to-cto-hermes-keystone`).
- Dùng cho service-call **project-scoped** (vd AAAA muốn 1 key mức platform/deal-project thay vì per-user).

### 3.2 user_id scoping LIVE (g2b) — ⚠️ NET-NEW (verified: hiện inert hoàn toàn)

> **Verified 2026-06-25:** `agent_context` handler chỉ resolve `project_id`+`DeveloperName`; `kg_recall` truyền `AgentRecallParams{ProjectID,...}` **không có UserID**; `resolveWriteIdentity` trả `(pid, DeveloperName)` → `source_agent`. **`user_id` không bao giờ được set/filter** ([agent_context.go:174,194-205]). `api_keys` **không có cột user_id**; link key→user duy nhất là `users.api_key_id` (**slot đơn** = web-session, không cho nhiều key/user). ⇒ g2b là net-new.

**Mảnh việc:**
1. **Migration: `api_keys.user_id UUID NULL` (FK users)** — key mang user. (D7 "resolve user_id from the agent key". Forward-link cho phép **nhiều key/user**, khác slot đơn `users.api_key_id`.)
2. **Auth carry user_id:** khi authenticate key → nạp `api_keys.user_id` vào `DeveloperIdentity` (thêm field `UserID`).
3. **Handler wiring (store KHÔNG đổi):** `resolveWriteIdentity` trả thêm user_id → `kg_remember` set `AgentContextParams.UserID = identity.UserID`; `kg_recall` set `AgentRecallParams.UserID`. Store đã có sẵn cả 2 field + filter (store:15/133/165) → chỉ handler truyền.
4. **Key-creation set user_id:**
   - JIT/login (`LoginWithSupabase`/`CreateUser`): set `api_keys.user_id` = user (ngoài `users.api_key_id`).
   - Dashboard "Create Key" (`apikey_mgmt`): thêm **optional "for user"** → set `user_id`. Key standalone hiện tại (Test 1, Platform Admin, Python Worker) = `user_id` NULL = project-scope (đúng, không vỡ).
   - Token-exchange consumer (§3.3): set `user_id`.
- **Precedence:** key có `user_id` → user-scope; NULL → project-scope (P0, không regression).

### 3.3 Token-exchange dùng được cho consumer (Q-1 RESOLVED)
- `/auth/supabase` trả key user-scoped để consumer **cache + dùng làm Bearer**.
- **Quyết:** key mint cho consumer dùng **label riêng** (vd `consumer-session-<user>`), **KHÔNG** dùng `web-session-*`. Lý do: `Login`/`LoginWithSupabase` **revoke key `web-session-*` cũ mỗi lần login** ([user.go:362-373]) → nếu consumer cache `web-session` key sẽ bị thu hồi khi user login dashboard. Label riêng → không bị revoke-churn, cache an toàn. Cùng endpoint + cùng bảng `api_keys`, chỉ phân biệt label/class.
- Cơ chế chọn label: `/auth/supabase` nhận tham số/header báo "consumer exchange" (vd `?session=consumer` hoặc header `X-KG-Client: consumer`) → mint key label `consumer-session-*` (không revoke web-session của user, và không bị web-session-login revoke). Human dashboard login giữ nguyên `web-session-*`.
- **Key mint phải set `api_keys.user_id`** (§3.2) = user vừa verify → để memory user-scope hoạt động.
- **KHÔNG** thêm loại key nặng mới; tái dùng plumbing key hiện có.

### 3.4 Test isolation user-level (T6/T7)
- Mở rộng `recall_isolation_test`: 2 user cùng project → user A không recall được memory user B; key user-scoped chỉ thấy của mình; key project-only thấy project-scope.

## 4. Decisions (RESOLVED 2026-06-25)
- **Q-1 → Reuse `/auth/supabase`, label riêng `consumer-session-*`** (xem §3.3). Không thêm key-type nặng.
- **Q-2 → Deal = `tags`/`mem_key`, KHÔNG phải DAAB project.** Scope axes giữ `project_id`+`user_id` (từ key); AAAA deal (Project AAAA) biểu diễn `tags:["deal:<aaaa-project-id>"]`, scope theo user. Tránh key-per-deal sprawl. Không đổi primitive DAAB.
- **Q-3 → Dashboard API-key dùng được cho human-MCP, NHƯNG cần thêm "for user"** (verified: hiện key dashboard standalone, KHÔNG user_id → chỉ project-scope). Plan: `apikey_mgmt.CreateKey` thêm optional `user_id`; user tạo "personal key" gắn chính họ → key→user_id → memory user-scope. (Không gắn user → project-scope, vẫn hợp lệ.)

## 5. Success criteria
- Key user-scoped → `kg_remember` ghi đúng `user_id`; `kg_recall` chỉ trả memory của user đó (T6/T7 xanh).
- Key project-only → project-scope như P0 (không regression).
- Consumer-key policy chặn cấu hình nguy hiểm, không phá admin-all.
- `go build` + `recall_isolation_test` + handler/middleware tests xanh `-race`.
- Không regression: project-scope memory (P0) + login/key flows hiện có vẫn chạy.

## 6. Out of scope / follow-ups
- Phát hành key thật cho AAAA/LAAM (vận hành).
- AAAA-side tích hợp (gọi `/auth/supabase`, cache key, gọi kg_recall) — việc của AAAA, sau khi DAAB sẵn sàng.
- `knowledge_nodes.user_id`, retention, kg_search_sessions.

---

## Verified facts (2026-06-25)
- `recall_isolation_test` xanh (project isolation, g2a done).
- ⚠️ **user-scope INERT:** store ĐÃ sẵn — `AgentContextParams.UserID` (write, store:15 "empty→NULL"), `AgentRecallParams.UserID` (recall, store:133 "empty→no filter"), filter `AND a.user_id` (store:165). **Handler không bao giờ truyền**: `resolveWriteIdentity`→`(pid, DeveloperName)` (không user_id); recall set `AgentRecallParams` không có UserID ([agent_context.go:174,194-205]). → chỉ thiếu wiring handler + nguồn user_id.
- ⚠️ **`api_keys` KHÔNG có cột `user_id`** (migration 003 + 011 default-project + 012 override; không có user_id). Link key→user duy nhất = `users.api_key_id` (slot đơn, web-session). → g2b cần thêm `api_keys.user_id`.
- `DeveloperIdentity` (handler dùng) chưa có UserID; có `UserIdentity{UserID}` riêng (auth.go:25, resolve qua users.api_key_id) nhưng handler memory không dùng.
- `Login` (user.go:362-381) + `LoginWithSupabase` (cùng pattern) mint key label `web-session-<username>` + revoke web-session cũ → consumer cần label riêng `consumer-session-*` (§3.3).
- AAAA: no tenant_id, scope=userId, deal=Project, Supabase Auth, Inngest server-side, chưa nối DAAB (`other_projects/am-ai-agents/prisma/schema.prisma`, `CLAUDE.md`). Cả AAAA+LAAM nối qua MCP (`decisions/ecosystem-hermes-allocation`).
- `APIKey` model có `Role` (admin/developer/agent/viewer) + `ProjectIDs` + `AllowProjectOverride`.
- Gate-0: `global/ecosystem/shared-memory-contract` KHÔNG ở store local (ở orchestrator); `backlog/cto-directives-2026-06-23` (local, ratified) đã xác nhận D3/D7/g2b. MCP Serena đã hoạt động lại.
