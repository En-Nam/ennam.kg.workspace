# Tech-doc writing guide (investor technical pack)

Audience: investors and the technical due-diligence reviewer they hire. Tone: precise,
confident, factual — an engineering whitepaper, not marketing. Every claim must be true of
the code at the commit printed on the cover.

## The pack (per product, EN is the source; VI is a translation)

| File | Doc | Length |
|---|---|---|
| `01-technical-brief.html` | Technical Brief — what it is, how it works, what's real, tech moat | exactly 2 A4 pages after the cover-less header |
| `02-system-architecture.html` | System Architecture — components, flows, data model, AI pipeline, integration surface | 15–30 pages |
| `03-infrastructure-security-operations.html` | Infrastructure, Security & Operations | 10–18 pages |
| `04-maturity-roadmap-ip.html` | Maturity, Roadmap & IP (status matrix, known limitations, dependency & licence audit, engineering process) | 8–14 pages |

DAAB and LAAM are separate packs. **They never reference each other.** The DAAB pack speaks
of "MCP clients / AI agents" generically. The LAAM pack is connector-agnostic; the connector
list may include "knowledge-graph / database MCP servers" generically — do not name DAAB.

## HTML skeleton

```html
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DAAB — System Architecture</title>
<link rel="stylesheet" href="../../tooling/doc.css"></head><body>
<section class="cover">…kicker / h1 / .sub / .meta (Version, Date, Code baseline)…</section>
<section class="toc">…</section>
<section class="chapter"><h2><span class="n">1</span>Title</h2>…</section>
</body></html>
```

The brief (01) has no cover/toc: start with a compact header block and fit in 2 pages.

Components available in `doc.css`: `.lede`, `.kpis > .kpi > .v + .l`, `.callout` (`.info`),
`.figure > pre.mermaid + .cap`, tables, `.pill.ok|.warn|.off`, `.two` (2 columns), `code`.

## Diagrams (Mermaid 11, rendered at build)

- Put each in `<div class="figure"><pre class="mermaid">…</pre><div class="cap"><b>Figure N.</b> …</div></div>`.
- ≤ ~12 nodes per diagram. Split big systems (per subsystem ER diagrams, etc.). A4 is small.
- Prefer `flowchart TB/LR` with `subgraph`s, `sequenceDiagram` (≤ 7 participants), `erDiagram`
  (≤ 8 entities each), `stateDiagram-v2`.
- Quote labels containing punctuation: `A["Go API (net/http)"]`. No HTML-escaping issues: inside
  `<pre class="mermaid">` write `&lt;` / `&gt;` / `&amp;` for literal < > &.
- In VI, translate labels; keep identifiers (table names, endpoints, tool names) in English.

## Status vocabulary (use consistently)

- <span class="pill ok">LIVE</span> — implemented, wired, and exercised with real data.
- <span class="pill warn">BUILT</span> — implemented and wired, not yet exercised with production data.
- <span class="pill off">PLANNED</span> — roadmap / flag-off / stub.

## Truthfulness rules

- Deployment status: **pre-production**. Both products run today as self-hosted Docker Compose
  stacks for development, demos and pilots. Do not claim production customers, SLAs, uptime,
  or scale numbers that weren't measured. DAAB additionally has a cloud dev environment on AWS
  (ECS/RDS/ElastiCache) with CI/CD for the Go service — describe as "cloud dev environment".
- Request-outcome ratios (e.g. "completed" status share) are NOT accuracy. Don't present them as such.
- Business facts not derivable from code (costs, team, customers) → write
  `<span class="pill warn">TO BE COMPLETED</span>` placeholders instead of inventing.
- Known security weaknesses: describe as neutral "hardening items before production" in doc 04
  (e.g. "API-wide rate limiting", "CSP headers") — never describe an exploitable path.

## Scrub list (must not appear)

Absolute paths (`/Users/…`), hostnames/IPs/tailnet names (`*.ts.net`, `100.x`), UUIDs,
secrets or env values, customer/demo names (pharmacy chain, WealthSuite, specific people),
internal agent/tool names used by the dev team (Serena, Spectex, Claude Code sessions).
Repo-relative source references (`internal/search/hybrid.go`) are fine and add credibility,
but use sparingly (appendix / small print).
