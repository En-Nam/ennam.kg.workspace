# Checkpoint: claude — 2026-09-24 (investor tech-doc packs)

## What was done
- Built investor/tech-DD documentation packs for DAAB and LAAM (separate, never cross-reference): 01 Technical Brief (2p), 02 System Architecture, 03 Infrastructure/Security/Ops, 04 Maturity/Roadmap/IP — each EN + VI → 16 PDFs.
- Facts researched from code (5 read-only research agents), baseline: go@16dc548, python@6966d4b, next@907bc8b, LAAM@7eb0724.

## Files changed
- Created docs/tech_docs/ (README.md, tooling/{render.mjs,build.mjs,doc.css,WRITING-GUIDE.md,TRANSLATION-GUIDE.md,package.json}, daab|laam/{en,vi}/0[1-4]-*.html, pdf/*.pdf). Nothing committed.

## Current state
- All 16 PDFs render clean (`cd docs/tech_docs/tooling && node build.mjs`). Scrub grep clean.
- TO BE COMPLETED placeholders (legal entity, IP assignment, team, pilots, backups/RPO, pen-test, VieNeu licences) await business input.

## Findings surfaced to user (NOT in investor docs)
- DAAB: dashboard /api/kg proxy falls back to KG_API_KEY without session; requireProjectRole passes user-less keys; POST /ai-queries lacks body project check; GenerateKG IDOR still open; migration 000009 seeds plaintext admin dev key; kg_get_context & kg_get_impact_analysis MCP tools route to non-existent server paths (404); deploy workflow calls non-existent `kg-server migrate`; Redis image floats to 7.4 (RSAL/SSPL); pymssql LGPL.
- LAAM: react-leaflet Hippocratic-2.1 licence; "Emma" voice clip provenance unclear; DAAB named in synthesizePlan.ts prompt; no CI; 6 failing tests / 90 lint errors.

## Next steps
- User to decide: keep "58% AI-assisted commits" figure; fix tests/lint before re-issuing; fill TO BE COMPLETED; decide on committing docs/tech_docs.
