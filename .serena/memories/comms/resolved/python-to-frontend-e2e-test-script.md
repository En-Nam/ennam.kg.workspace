# E2E Test Script: AI Chat Feature — For Frontend Team

**Date**: 2026-05-05
**From**: Python Team
**To**: Frontend Team
**Re**: Kịch bản test end-to-end cho AI Chat sau refactor Python worker

---

## Prerequisites

```bash
docker compose up -d          # All services running
# Verify: http://localhost:8080/healthz (Go API)
# Verify: http://localhost:8081/healthz (Python worker)
# Verify: http://localhost:3500 (NextJS dashboard)
```

Đảm bảo:
- Go API có active AI provider (Anthropic key trong `ai_providers` table)
- Có ít nhất 1 data source với schema đã extract (C4K Staging hoặc test DB)
- Admin user login được

---

## Test Case 1: Happy Path — Basic Chat Query

**Mục đích**: Verify full streaming pipeline hoạt động end-to-end

**Steps:**
1. Login as admin → navigate to `/chat`
2. Chọn data source (ví dụ: "C4K Staging" hoặc data source có sẵn)
3. Tạo thread mới hoặc chọn thread trống
4. Gõ: `Show me top 10 orders`
5. Click Send

**Expected:**
- [ ] User message xuất hiện ngay trong chat bubble
- [ ] Loading/progress indicators hiện ra theo sequence:
  - "Understanding your question..." (parsing_intent)
  - "Generating SQL query..." (generating_sql)
  - "Running query..." (executing_query)
  - "Analyzing results..." (generating_response)
- [ ] Assistant response xuất hiện progressively (word by word streaming)
- [ ] Rich content blocks render sau khi text streaming xong:
  - Markdown summary block
  - Table block với data (hoặc chart nếu applicable)
- [ ] Suggested actions xuất hiện (3 buttons) — ví dụ: "Drill down", "Export CSV", "Compare"
- [ ] Không có error messages

**Verify in DevTools (Network tab):**
- [ ] Request to BFF: `POST /api/kg/ai-query/stream`
- [ ] Response type: `text/event-stream`
- [ ] SSE events visible in EventStream tab (nếu Chrome)

---

## Test Case 2: Multi-turn Conversation

**Mục đích**: Verify context window hoạt động

**Steps:**
1. Trong cùng thread từ Test 1
2. Gõ: `What about last month?`
3. Click Send

**Expected:**
- [ ] AI response liên quan đến context trước (orders last month, không phải random)
- [ ] Progress indicators hiện lại
- [ ] Streaming response mới xuất hiện
- [ ] Thread message count tăng (2 user + 2 assistant = 4)

---

## Test Case 3: Error Recovery — Invalid Query

**Mục đích**: Verify error handling và retry

**Steps:**
1. Gõ một query không liên quan đến schema: `Show me weather forecast for tomorrow`
2. Click Send

**Expected:**
- [ ] Error message xuất hiện trong red bubble
- [ ] Error message readable (không phải raw JSON hoặc stack trace)
- [ ] Nếu `retryable=true` → Retry button hiện
- [ ] Nếu `retryable=false` → Chỉ error message, không có Retry
- [ ] Thread không bị crash — có thể tiếp tục gõ message mới

---

## Test Case 4: Suggested Actions — Query Follow-up

**Mục đích**: Verify suggested actions auto-send

**Steps:**
1. Từ một response thành công (Test 1)
2. Click vào suggested action có `action_type="query"` (ví dụ: "Drill down" hoặc "Show by region")

**Expected:**
- [ ] Chat input auto-fill với query text từ action
- [ ] Message tự động gửi (hoặc user confirm — tùy UX design)
- [ ] New streaming response bắt đầu cho follow-up query

---

## Test Case 5: Rich Response — Table Block

**Mục đích**: Verify table rendering

**Steps:**
1. Gõ: `List all customers with their email and phone`
2. Click Send

**Expected:**
- [ ] Summary text streaming trước
- [ ] Table block render với:
  - Column headers (id, name, email, phone hoặc tương tự)
  - Data rows
  - Pagination nếu > 10 rows
- [ ] Table data đúng (không empty, không garbled)

---

## Test Case 6: Rich Response — Chart Block

**Mục đích**: Verify chart rendering

**Steps:**
1. Gõ: `Show total sales by month for the last 6 months`
2. Click Send

**Expected:**
- [ ] `format_metadata` event có `format: "chart"` (verify in DevTools)
- [ ] Chart renders (bar hoặc line chart)
- [ ] Axes labeled correctly
- [ ] Data points match query results
- [ ] Nếu không có chart data → graceful fallback to table

---

## Test Case 7: Code Block (SQL Display)

**Mục đích**: Verify SQL code block rendering

**Steps:**
1. Từ bất kỳ successful response
2. Check xem có code block hiện SQL generated không

**Expected:**
- [ ] Code block với syntax highlighting (SQL)
- [ ] SQL readable và hợp lệ
- [ ] Copy button (nếu có) hoạt động

---

## Test Case 8: Thread Management

**Mục đích**: Verify thread CRUD

**Steps:**
1. Tạo thread mới → verify thread xuất hiện trong sidebar
2. Rename thread → verify tên mới hiển thị
3. Switch giữa threads → verify messages load đúng
4. Archive thread → verify thread biến mất khỏi active list

**Expected:**
- [ ] Thread list sorted by last_message_at (newest first)
- [ ] Thread name auto-generated từ first message (nếu không manual rename)
- [ ] Switching threads loads correct message history
- [ ] Archived threads không hiện trong default view

---

## Test Case 9: Disconnect / Timeout Handling

**Mục đích**: Verify FE handles connection issues gracefully

**Steps:**
1. Start a query
2. While streaming: mở DevTools → Network tab → Block `localhost:8081` (hoặc throttle to offline)
3. Observe behavior

**Expected:**
- [ ] Sau timeout (~5 phút hoặc network error): error message hiện
- [ ] Error message: "Stream timed out" hoặc "Connection lost"
- [ ] Không crash, không infinite spinner
- [ ] Có thể retry hoặc gõ message mới

---

## Test Case 10: MSSQL Data Source

**Mục đích**: Verify MSSQL dialect (nếu có MSSQL data source)

**Steps:**
1. Chọn MSSQL data source (C4K Staging)
2. Gõ: `Show top 5 products by price`
3. Click Send

**Expected:**
- [ ] Query thành công (không SQL syntax error)
- [ ] Generated SQL dùng `SELECT TOP 5` (không `LIMIT 5`) — verify trong code block hoặc DevTools
- [ ] Results hiện đúng

---

## SSE Events Reference (DevTools Debugging)

Nếu cần debug, mở DevTools → Network → chọn stream request → tab EventStream:

```
✓ progress (4x: parsing_intent → generating_sql → executing_query → generating_response)
✓ format_metadata (1x: format type + block count)
✓ content (Nx: word-by-word streaming)
✓ block_start → block_content → block_end (per block)
✓ suggested_actions (1x: 3 actions)
✓ done (1x: final metadata)
```

Nếu thấy `error` event:
- `INTENT_PARSE_FAILED` → AI không hiểu query (có thể do schema chưa extract)
- `AI_PROVIDER_ERROR` → Anthropic API issue (check API key)
- `QUERY_EXECUTION_FAILED` → SQL error on source DB
- `STREAM_TIMEOUT` → quá 5 phút

---

## Regression Checks

Sau khi test xong happy path, verify các feature cũ vẫn hoạt động:

- [ ] Health page (`/healthz` endpoints) — green
- [ ] KG visualization (graph view) — nodes render
- [ ] Data source management — list, connect, sync
- [ ] Settings page — loads without error
- [ ] Login/logout — works normally

---

## Bug Reporting Template

Nếu phát hiện bug, report lên Serena (`comms/frontend-bug-report-<feature>`) với format:

```
**Steps to reproduce**: 1. ... 2. ... 3. ...
**Expected**: ...
**Actual**: ...
**SSE trace** (from DevTools): paste raw events
**Screenshot**: (if applicable)
**Browser**: Chrome/Firefox + version
```
