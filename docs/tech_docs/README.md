# Technical documentation packs — DAAB & LAAM

Investor / technical-due-diligence documentation. Two **independent** packs (they never
reference each other), each in English (source) and Vietnamese (translation).

| # | Document | Purpose |
|---|---|---|
| 01 | Technical Brief | 2 pages — send with the pitch |
| 02 | System Architecture | Components, flows, data model, AI pipeline, integration surface |
| 03 | Infrastructure, Security & Operations | Deployment topology, security model, AI data flow, operations |
| 04 | Maturity, Roadmap & IP | Status matrix (LIVE / BUILT / PLANNED), limitations, roadmap, licence audit |

PDFs: `pdf/<PRODUCT>-<NN>-<name>-<EN|VI>.pdf` (16 files).

## Code baseline (2026-09-24)

| Product | Repos @ commit |
|---|---|
| DAAB | `ennam.kg.go` @ 16dc548 · `ennam.kg.python` @ 6966d4b · `ennam.kg.next` @ 907bc8b |
| LAAM | `LAAM` @ 7eb0724 |

Every figure in the documents was measured against these commits. When the code moves,
re-verify numbers before re-issuing.

## Open items to complete before sharing

Placeholders are marked **TO BE COMPLETED** in the PDFs (search the HTML for `TO BE COMPLETED`).
They cover facts code cannot provide: legal entity, contributor IP assignment, team size,
pilots/customers, hosting model, backup/RPO/RTO, pen-test, provider data-processing terms,
VieNeu TTS package/model licences, English voice clip provenance.

## Rebuild

```bash
cd docs/tech_docs/tooling
npm install            # once: mermaid + puppeteer-core (uses local Google Chrome)
node build.mjs         # all 16 PDFs
node build.mjs daab/vi # a subset (path filter)
```

Sources: `daab|laam/{en,vi}/NN-*.html`, shared styles `tooling/doc.css`, renderer
`tooling/render.mjs`. Diagrams are drawn by the documents themselves
(`tooling/mermaid-init.js` + the local Mermaid package), so the HTML files show the same
diagrams as the PDFs when opened in a browser — after `npm install` has been run in
`tooling/` once. Share the PDFs, not the HTML. Writing and translation rules: `tooling/WRITING-GUIDE.md`,
`tooling/TRANSLATION-GUIDE.md`. Diagrams are Mermaid, rendered at build time
(needs network for Google Fonts: Be Vietnam Pro, JetBrains Mono).
