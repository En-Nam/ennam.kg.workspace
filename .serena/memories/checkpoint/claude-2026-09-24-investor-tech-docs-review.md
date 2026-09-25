# Checkpoint: claude — 2026-09-24 (tech-doc packs, review round 1)

## What was done
- Colour redesign of docs/tech_docs (per-product brand tokens in tooling/doc.css; full-bleed cover rendered separately via pdfunite; diagrams themed from CSS vars; diagrams render in-document via tooling/mermaid-init.js).
- 8 review agents (4 fact-check vs code, 2 EN↔VI fidelity, 2 PDF visual) → reports in session scratchpad; 8 fix agents (one per doc pair) applied fixes using tooling/FIX-BRIEF.md + tooling/GLOSSARY-VI.md.
- Build now warns on any diagram label < 6.5pt (width AND height scale); all 16 PDFs clean.

## Key corrections made to docs
- DAAB: NL "never raw SQL" scoped to MCP/API path (dashboard agentic chat writes SELECT); MCP tools "55 advertised / 53 wired"; benchmark not "human-validated" (30 groups, 86 pairs); cross-project read claim → hardening; hardening list 15 items identical in 03 §8 and 04 §5.3.
- LAAM: write-confirm is chat-only (workflow-safe tools write unattended to allow-listed recipients); no "exactly once"; SSRF wording (MCP DNS check vs web reader blocklist); MCP server hand-written JSON-RPC; connectors 11 + 1 demo; no-code-exec guard is a test, no CI.

## Code issues found (for engineering, NOT in docs)
- DAAB: GET /api/v1/nodes/{id} lacks project check (cross-tenant read in multi-tenant bridge); user-less keys skip project role; IsReadOnly never called; dashboard proxy service-key fallback.
- LAAM: web_read/fetch-url hostname-only SSRF check (no DNS, no 100.64/10); MCP SSRF DNS rebinding; confirm-nonce race + MCP retry after timeout; CONNECTOR_KEY falls back to AUTH_SECRET; X-Forwarded-For-keyed limiter; login timing; Adminer 0.0.0.0 + inline DB creds in compose.

## Next steps
- User decisions: TO BE COMPLETED fields, keep "58% AI-assisted", fix code issues before DD, commit docs/tech_docs?
