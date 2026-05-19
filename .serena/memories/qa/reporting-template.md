# QA Test Report Template

**Created**: 2026-04-15
**Usage**: QA agent writes reports to `.serena/memories/qa/reports/` using this format.

---

## Report File Naming

`qa/reports/{phase}-{date}-{type}.md`

Examples:
- `qa/reports/phase3-2026-04-15-e2e.md`
- `qa/reports/phase4-2026-04-15-regression.md`
- `qa/reports/smoke-2026-04-15.md`

---

## Report Template

```markdown
# QA Report: Phase {N} — {Test Type}

**Date**: {YYYY-MM-DD}
**Tester**: {agent-name}
**Environment**: localhost (Docker Compose)
**Duration**: {total time}
**BA Scope**: BA-{XXX} through BA-{YYY}

---

## Summary

| Metric | Count |
|--------|-------|
| Total Test Cases | {N} |
| Passed | {N} (✅) |
| Failed | {N} (❌) |
| Skipped | {N} (⏭️) |
| Blocked | {N} (🚫) |
| Pass Rate | {N}% |

## Critical Failures (P0/P1)

| TC ID | Title | BA Ref | Severity | Assigned Team | Details |
|-------|-------|--------|----------|---------------|---------|
| TC-P3-014-003-01 | Login fails with correct password | BA-014/FR-003 | P0 | Go API | Expected 200, got 500. Stack trace in console. |

## All Results

### BA-{XXX}: {Title}

| TC ID | Title | Status | Notes |
|-------|-------|--------|-------|
| TC-... | ... | ✅ Pass | |
| TC-... | ... | ❌ Fail | {brief reason} |
| TC-... | ... | ⏭️ Skip | {why skipped} |

### BA-{YYY}: {Title}
...

## Bug List

### BUG-{SEQ}: {Title}

**Severity**: P0 | P1 | P2 | P3
**BA Reference**: BA-{XXX}/FR-{YYY}
**Test Case**: TC-{...}
**Assigned Team**: Go API | NextJS | Python
**Status**: Open

**Steps to Reproduce**:
1. Navigate to {URL}
2. Click {element}
3. Observe {actual behavior}

**Expected**: {what should happen}
**Actual**: {what actually happened}

**Evidence**:
- Screenshot: {path or description}
- Console error: {error message}
- Network: {status code, response body}

**Environment**: Docker Compose, localhost:3500, Chrome 125

---

## Performance Observations

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Page load | < 2s | {N}s | ✅/❌ |
| First token | < 3s | {N}s | ✅/❌ |
| Chart render | < 2s | {N}s | ✅/❌ |

## Recommendations

- {action item for dev team}
- {action item for dev team}

## Next Steps

- [ ] Dev teams fix P0/P1 bugs
- [ ] QA re-test after fixes
- [ ] Proceed to next phase testing
```

---

## Bug Severity Guide

| Severity | Definition | Example |
|----------|-----------|---------|
| P0 Blocker | App unusable, data loss, security hole | Login always fails, SQL injection possible |
| P1 Critical | Core feature broken, no workaround | AI query returns error every time |
| P2 Major | Feature broken, workaround exists | Chart tooltip shows wrong values |
| P3 Minor | Cosmetic, UX annoyance | Button misaligned by 2px |

## Team Assignment Rules

| Area | Assign To |
|------|-----------|
| API returns wrong status/data | Go API team |
| API returns correctly but UI shows wrong | NextJS team |
| AI generates wrong SQL/insights | Python team |
| SSE streaming issues | Go API team (proxy) + Python team (generator) |
| Auth/session issues | Go API team (backend) + NextJS team (BFF/cookies) |
| Chart rendering issues | NextJS team |
| Database schema issues | Go API team (migrations) |

## Report Delivery

1. Write report to Serena: `write_memory("qa/reports/{filename}", content)`
2. Tag critical bugs with team assignment
3. Dev teams read: `read_memory("qa/reports/{filename}")`
4. After fixes: QA re-tests failed cases → update report status

## Screenshot Evidence

When capturing evidence via `browser_take_screenshot()`:
- Save path noted in bug report
- Include screenshots for ALL failures (not just visual bugs)
- Include console errors via `browser_console_messages()`
- Include network failures via `browser_network_requests()`
