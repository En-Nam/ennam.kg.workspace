# QA Verification Retest Fixes — 2026-04-16 (Round 2)

**Status**: ALL remaining Go API bugs FIXED
**Commit**: 2a69b6e on main

## Fixed

| # | Bug | Root Cause | Fix |
|---|-----|------------|-----|
| 1 | P1: Add Project Member 500 | resolveUserID() returned DeveloperName (string) not UUID | Now uses GetUserIdentity().UserID with DeveloperName fallback |
| 2 | P2: Node history 404 (route not found) | HistoryHandler never wired in composition root | Added historyStore + historyHandler.RegisterRoutes(apiMux) |

## Not Fixed (FE/Design — not Go API)
- P2: Chat Demo tooltip on disabled buttons (Radix UI limitation — needs wrapper span or native title)
- Login API key revocation design decision (deferred)
