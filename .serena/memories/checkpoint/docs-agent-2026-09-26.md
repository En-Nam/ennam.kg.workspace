# Checkpoint: docs-agent — 2026-09-26

## What was done
- tech_docs v1.1 (DAAB + LAAM, EN+VI, 16 HTML + 16 PDFs), baselines LAAM 355cbd6; DAAB go 88c132d · python 92f4666 · next 109e22e.
- Round 2 (user decision): docs cover ONLY customer-visible features; hidden features removed entirely (never "hidden/by URL"). 8 parallel agents fact-checked every doc pair vs code.
- LAAM: Custom Agents is a surface (BUILT); monitoring, MCP-server capability, proactive alerts, Reliability page removed; cost wording fixed (chat tokens + estimated cost for priced models; workflow cost recorded not displayed); host metrics not for voice.
- DAAB: dashboard chat/Decisions/Code map/Impact/Claude OAuth/benchmark removed; many fact fixes (no kg-migrate container, job engine unused, batch 100, breaker 5 fails/10-min reset, hub-guard bypass for exact names, BA table rows repaired, SSO = dashboard sign-in LIVE, 53 working MCP tools = 50 API + 3 local).
- Rules recorded in tooling/FIX-BRIEF.md "Superseded rules"; README updated.

## Current state
- All builds "(all diagrams ok)"; briefs 2 pages; pages: DAAB 2/31/18/14, LAAM 2/30(EN)31(VI)/18/16-17. Not committed.

## Next steps
- User review + commit in ennam.kg.requirements.
- Product gaps flagged to user: LAAM header Sync button + Search agent-session results still visible; DAAB Overview quick actions still link /decisions and /agents.

## Blockers / Risks
- Measured figures not checkable from code (eval scores, demo snapshot counts) carried over from v1.0.
