# Fix brief — review round 1 (2026-09-24)

You own exactly ONE document pair: `<product>/en/NN-*.html` and `<product>/vi/NN-*.html`.
Do not edit any other file (not doc.css, not tooling, not other docs). Use unique scratch
filenames prefixed with `<product>-NN-` if you need temp files.

Inputs:
- Review reports in `/private/tmp/claude-501/-Users-danhtrinh-Projects-Exnodes-EnnamKG-ennam-kg-workspace/13ed9d99-6589-4910-940b-7f4c40051ee3/scratchpad/review/`:
  `<product>-*-facts.md` (fact-check vs code), `<product>-vi-fidelity.md` (EN↔VI), `<product>-visual.md` (PDF layout).
  Only rows about YOUR doc number apply (cross-doc rows: apply the canonical wording below to your doc).
- `tooling/WRITING-GUIDE.md`, `tooling/TRANSLATION-GUIDE.md`, `tooling/GLOSSARY-VI.md` (binding for VI).
- Source code (read-only) to verify before changing a claim.

## Work, in order
1. **EN facts**: fix every HIGH and MED row for your doc. Verify against code yourself when the
   report is ambiguous. Prefer precise, honest wording over deleting content. Never describe an
   exploitable path — security weaknesses become neutral "hardening items before production".
2. **Mirror** every EN change into the VI file (same meaning, glossary terms).
3. **VI fidelity**: fix every HIGH and MED row for your doc; then apply `GLOSSARY-VI.md` across the
   whole VI file (terminology must match the glossary exactly, including status-vocabulary wording).
4. **Diagram legibility** (EN and VI): `node build.mjs <product>/<lang>/NN` prints
   `small diagram text (<6.5pt)` for every figure whose labels print below 6.5 pt. Make every
   figure ≥ 6.5 pt: diagrams now render at natural size (no upscaling), so the fix is to make
   wide diagrams narrower — switch LR→TB, wrap labels with `&lt;br/&gt;`, shorten labels, drop
   non-essential nodes/columns (ER: keep ≤ 5 key columns per entity), split one figure into two,
   or lift a local `max-height` cap that is shrinking it. Keep meaning identical between EN and VI.
   Also fix overlapping labels reported by the visual review.
5. **Layout** MED rows for your doc (stranded headings, large accidental gaps, orphan rows).
   Briefs (01) must stay exactly 2 pages with page 2 starting at "Where it stands today".
6. Rebuild both files; confirm: `(all diagrams ok)`, **no small-diagram warnings**, and read every
   page you changed (Read tool, PDF page ranges). Scrub grep from WRITING-GUIDE must stay clean.

Final reply: list of changes (EN facts, VI, diagrams, layout), page counts EN/VI, anything you
could not fix and why.

## Canonical cross-doc wording (apply wherever your doc touches these)

### LAAM
- **Write confirmation**: in chat, every write to a connected system waits for the user's
  confirmation of a code-built preview; the confirmed call uses the sealed arguments and its nonce
  is checked against the audit log. Scheduled/unattended workflows may execute writes only for
  tools marked workflow-safe and only to allow-listed recipients. Do NOT say "exactly once",
  "structurally impossible" or "every write waits for a human" without the chat qualifier.
  Hardening item: atomic nonce claim + idempotent retry for confirmed MCP writes.
- **SSRF**: user-added MCP server URLs are checked at connect time against private/metadata ranges
  after DNS resolution; the web reader / URL fetch uses a hostname blocklist. Hardening item: one
  DNS-pinned guard for all outbound fetches, carrier-grade NAT range, re-check on redirect.
- **Connectors**: "12 built-in connectors (11 integrations + 1 offline demo) · 46 tools".
- **Connector-agnostic**: the integration layer is generic; a few model-facing prompt strings still
  reference one knowledge-graph server's tools (cleanup tracked). Never name that server.
- **No-code-execution guard**: a test in the suite fails (not "the build"); there is no CI yet.
- **LAAM's MCP server**: hand-written JSON-RPC over Streamable HTTP (the MCP *client* uses the
  official SDK).
- **Chat model check**: Claude model ids are checked against an allow-list; other ids go to the
  local runtime.
- **Route authorization**: state-changing *business* routes require a mutating role; some
  personal/helper routes need only a session.
- **Deployment wording**: "development, internal use and demonstrations" — never "pilots"
  (pilots are TO BE COMPLETED).
- **Tool-count eval**: do not claim "flat from 4 to 60 tools". Say: an early low-sample run
  suggested stable selection as tools grew; a later 60-tool run averaged 67% — scaling is still
  being measured.
- **Status pills (use doc 04 as canonical)**: workflow engine LIVE; AI authoring BUILT; cron
  scheduler BUILT; access control LIVE; credential encryption LIVE; global search BUILT;
  MCP server BUILT; monitoring LIVE.
- **Auth library**: Auth.js v5 beta (next-auth 5.0.0-beta.31).

### DAAB
- **NL data query**: the agent/API path (MCP `kg_query_datasource`) has the LLM produce a query
  plan that the server validates and renders as parameterised, read-only SQL (READ ONLY session on
  PostgreSQL sources). The dashboard's agentic chat mode lets the model write SELECT statements,
  checked by a read-only validator with row caps. Never claim "never raw SQL" for the dashboard.
- **Controlled writes**: LIVE (small volume) everywhere.
- **Deployment**: dev Compose stack LIVE; release bundle v1.0.0 BUILT; AWS cloud dev environment
  BUILT; production PLANNED.
- **Entity-resolution benchmark**: "a small internal Vietnamese benchmark (30 entity groups,
  86 duplicate pairs): precision 1.000, recall 0.915" — do NOT say "human-validated".
- **Data sources**: "9 registered data sources (5 active, 852 tables)"; API keys "80 issued (16 active)".
- **Tests**: Go 2,753 test functions; Python 943 tests collected (915 `test_` functions); web: no tests.
  Ruff: 16 findings (2 in source, 14 in tests). Dashboard ESLint: 27 errors, 28 warnings.
- **Deployment wording**: "development and demonstrations" — never "pilots".
- **Specs**: phase-1 specs were written after the phase-1 code; improvement specs are lighter
  (no numbered use cases). Don't claim all 43 were "reviewed before build".
- **Hardening list**: doc 03 §8 and doc 04 §5.3 must list the same items (use the union).
- **MCP tool count**: 55 tools are advertised; 53 are wired to server routes (2 have no route
  yet → PLANNED); 2 of the 53 are local code-indexing tools that need the indexer installed on the
  agent's host. Keep the KPI "53" but label it "MCP tools wired to the API" (VI: "tool MCP đã nối API").
- **Project isolation**: do NOT claim cross-project reads return not-found everywhere. Say project
  scope is enforced by middleware and on project-scoped handlers; uniform per-project checks on
  every by-ID read and for keys not linked to a user are a hardening item (same item in 03 §8 and
  04 §5.3).
- **History**: node versions are append-only for graph edits; document regeneration replaces a
  document's sections/chunks (and their history rows). Don't say "never hard-deleted" unqualified.
- **Stalled-extraction recovery sweep**: implemented but not scheduled → PLANNED (02 must match 03).
- **Dashboard chat data path**: the Python indexer connects directly to customer databases for
  dashboard chat (decrypts the connection string itself; no database-level read-only session) —
  show it in the trust-boundary diagram and data-flow text.
- **Unverified figures**: remove "blocking recall 0.901" (not in any repo report).
- **SSE**: at most 3 concurrent chat streams per user.
