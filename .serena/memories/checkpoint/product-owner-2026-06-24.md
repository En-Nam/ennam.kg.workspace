# Checkpoint: product-owner (marketing home page) — 2026-06-24

## What was done
- Acted as PO; ran a counter-arguing design panel (14 agents: 3 Designers x lenses → Taste/Feasibility/QA critics → synthesis → completeness) to design DAAB's public marketing home page.
- Completeness critic caught a Rule 13 fabrication (recited "13 node / 8 edge / 32 MCP / 35 migrations / 6 code types"). Verified ground truth from source: **20 node types, 25 relationship types, 49 whitelist rules, 35 MCP tools (schema.go:190), 31 dashboard pages, 4 graph layout modes**; NFRs <500ms/<200ms/<10ms real (BA-001). Code symbols are `architecture` nodes with `properties.kind` — NO first-class code node types. Parsers: TS+Python real, Dart stub.
- Built the full coded page: public marketing landing now owns `/`; dashboard overview relocated to `/dashboard` (login redirect + sidebar updated).
- Design: dark anti-slop, single accent Observatory Teal `#5FB8A6`, live WebGL 3D knowledge-graph hero (react-force-graph-3d, bloom OFF, cooldownTicks=0 pre-baked sphere, orbit auto-rotate, static-poster-first LCP, full reduced-motion/no-WebGL/save-data fallbacks + keyboard Pause/Play + figure aria text equivalent). 9 sections, all real components on static fixtures (no fake screenshots). Bilingual VI-first + EN via typed dict (`en satisfies Dict`) + cookie `daab_lang`.
- **Font deviation (verified):** Poppins has NO `vietnamese` subset → marketing uses **Be Vietnam Pro** + JetBrains Mono, scoped to (marketing) only; dashboard keeps Poppins.
- Added `motion` 12.41.0 (only new dep). QA pass applied (em-dashes removed, contrast bumped to >=7.47:1, reduced-motion connector fixed, 44px targets, React 19 react-hooks rules satisfied).

## Files changed
- NEW: `ennam.kg.next/src/app/(marketing)/` — layout.tsx, page.tsx, marketing.css, lib/{schema,dict,locale,graphPalette,useReducedMotion,fixtures/{graph,content}}, components/{HeroGraph,HeroGraphWrapper,StaticConstellation,Reveal,CountUp,Cta,LanguageToggle,MarketingNav,MarketingFooter,MarketingNodeCard,MiniGraph,Sparkline,SkipLink}, sections/{Hero,Problem,Extraction,DualAccess,Enforcement,Performance,TypeSystem,Cost,ClosingCta}
- MOVED: `(dashboard)/page.tsx` → `(dashboard)/dashboard/page.tsx`
- MODIFIED: `(auth)/login/actions.ts` (redirect /→/dashboard), `components/layout/Sidebar.tsx` (/→/dashboard), `package.json` (+motion)
- DOCS: `docs/superpowers/specs/2026-06-24-daab-marketing-home-design.md`, `docs/superpowers/plans/2026-06-24-daab-marketing-home.md`

## Current state
- `npm run build` PASSES (exit 0). Route table: `/`=marketing (dynamic), `/dashboard`=overview. `npx eslint "src/app/(marketing)"` = 0 errors, 1 benign warning.
- Not git-committed (awaiting user). Not run in a browser yet (Lighthouse/visual + VI diacritic render unverified live).

## Next steps
- Optional: run dev server + Lighthouse (LCP<2.5s/CLS<0.1/INP<200ms), visually verify VI diacritics + the 3D hero, keyboard/reduced-motion pass.
- Render the OG 1200x630 + hero PNG poster (currently CSS/SVG poster only).
- Commit when the user asks.

## Blockers / Risks
- Pre-existing (NOT mine, left per surgical rule): repo `react-hooks/set-state-in-effect` lint errors in `lib/context/*`; login redirect uses `.message==='NEXT_REDIRECT'` (works on Next 16.2.1; harden to `isRedirectError` before upgrade).
- Reading `daab_lang` cookie opts `/` into dynamic rendering (accepted; poster is still LCP).
