# DAAB Marketing Home Page — Implementation Plan

> **For agentic workers:** This plan is executed INLINE in the current session (PO chose to proceed). It is the build contract for the spec at `docs/superpowers/specs/2026-06-24-daab-marketing-home-design.md`. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Ship a public, Vietnamese-first marketing landing at `/` for the Ennam Knowledge Graph (DAAB), with a live WebGL knowledge-graph hero, 9 anti-slop sections built from real components on static fixtures, restrained motion, and full a11y — verified by `npm run build` + `npm run lint`.

**Architecture:** New `src/app/(marketing)/` route group claims `/`. The existing auth-gated overview moves from `(dashboard)/page.tsx` to `(dashboard)/dashboard/page.tsx`. The marketing subtree inherits the root layout's providers (inert — nothing fetches) and visually overrides the cyberpunk theme via a scoped `[data-surface="marketing"]` wrapper that paints an opaque canvas over the body grid and redefines CSS variables. All data is static fixtures (the public route cannot call the auth'd BFF). Exactly one WebGL context (the hero); every other graph echo is 2D/SVG.

**Tech Stack:** Next.js 16.2.1 (App Router, RSC) · React 19 · Tailwind v4 · `react-force-graph-3d` + `three` (installed) · `recharts` (installed) · `motion` (NEW) · Poppins + JetBrains Mono (`next/font`) · lucide-react (strokeWidth 1.5) · TypeScript strict.

## Global Constraints (verbatim from spec)

- Dark anti-slop only. Canvas `#0A0B0D`, surfaces `#121417`/`#171A1E`, text `#ECEDEF`, muted `#9AA0A8`.
- ONE accent page-wide: Observatory Teal `#5FB8A6` (<80% sat); `--accent-foreground #0A0B0D` (white-on-teal FORBIDDEN).
- One radius scale: 16px cards / 8px inputs+chips / full-pill buttons. One theme. No section inversion.
- NEVER import `src/lib/graph/styles.ts`; NEVER use `.glass`/`.glow`/`.text-glow`/`.neon-*`; bloom OFF on the hero.
- Every visible string is bilingual (vi + en), vi authored first; `en satisfies typeof vi`.
- Real components on static fixtures only — no div fake-screenshots, no live BFF calls, no picsum, no fabricated logos.
- All numbers source-verified (Appendix A of the spec): 20 node types, 25 relationship types, 49 whitelist rules, 35 MCP tools (verify at build), 31 dashboard pages, 4 layout modes, `<500ms`/`<200ms`/`<10ms` NFRs. Code symbols = `architecture` nodes with `properties.kind`. Parsers: TS + Python (Dart roadmap).
- Motion dial 5, tiered; `prefers-reduced-motion` is authoritative; "motion claimed = motion shown"; zero marquees; one WebGL context.
- WCAG AA: hero canvas decorative (`aria-hidden`) with bilingual text equivalent + keyboard Pause/Play; every hover highlight also fires on `:focus`; tap targets ≥44px; contrast ratios per token table.
- Next 16: `ssr:false` only inside `'use client'`; `cookies()` is async (opts route into dynamic rendering — accepted); `themeColor` via `export const viewport`, not metadata.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/app/layout.tsx` (MODIFY) | add `'latin-ext','vietnamese'` subsets + `display:'swap'` to Poppins & JetBrains_Mono (VN glyph fix, app-wide) |
| `src/app/(marketing)/layout.tsx` | RSC; reads `daab_lang` cookie; `generateMetadata` + `viewport`; scoped `<div data-surface="marketing" lang>`; mounts `LocaleProvider`; imports `marketing.css` |
| `src/app/(marketing)/marketing.css` | `[data-surface="marketing"]` token overrides + `background-color` canvas + utility resets |
| `src/app/(marketing)/page.tsx` | RSC; composes the 9 sections + nav + footer |
| `src/app/(marketing)/lib/schema.ts` | `NODE_TYPES`/`EDGE_TYPES` const tuples + `NodeType`/`EdgeType` unions (the real taxonomy contract) |
| `src/app/(marketing)/lib/dict.ts` | `vi` + `en` typed dictionary (`en satisfies typeof vi`) |
| `src/app/(marketing)/lib/locale.tsx` | `'use client'` `LocaleProvider` + `useT()` + `useLocale()`; persists `daab_lang` |
| `src/app/(marketing)/lib/graphPalette.ts` | zinc-tint + teal node/edge color maps (does NOT import styles.ts) |
| `src/app/(marketing)/lib/useReducedMotion.ts` | `'use client'` shared reduced-motion + saveData + capability gate hook |
| `src/app/(marketing)/lib/fixtures/graph.ts` | ≤80 nodes / ~140 edges with pre-baked x/y/z, typed to schema |
| `src/app/(marketing)/lib/fixtures/content.ts` | mcpTools, codeSnippet+extractedNode, gates, perf, nodeTypes, cost fixtures |
| `src/app/(marketing)/lib/fixtures/fixtures.test.ts` | asserts every fixture node/edge type ∈ schema unions |
| `src/app/(marketing)/components/HeroGraph.tsx` | `'use client'` leaf; `ForceGraph3D`; bloom off; freeze after cooldown; IO teardown |
| `src/app/(marketing)/components/HeroGraphWrapper.tsx` | `'use client'`; `dynamic(()=>import('./HeroGraph'),{ssr:false,loading:StaticConstellation})` + memo + capability gate |
| `src/app/(marketing)/components/StaticConstellation.tsx` | CSS/SVG dot constellation poster (the LCP-safe default) |
| `src/app/(marketing)/components/Reveal.tsx` | `'use client'`; `motion` `whileInView` wrapper honoring reduced-motion |
| `src/app/(marketing)/components/CountUp.tsx` | `'use client'`; count-up once on view, final value in DOM, `aria-hidden` anim layer |
| `src/app/(marketing)/components/Cta.tsx` | teal-fill / ghost CTA as `Link`/anchor; scroll-to-hero behavior |
| `src/app/(marketing)/components/LanguageToggle.tsx` | `'use client'`; VI|EN radiogroup; sets cookie + div lang |
| `src/app/(marketing)/components/MarketingNav.tsx` | floating nav: wordmark, lang toggle, Login button |
| `src/app/(marketing)/components/MarketingFooter.tsx` | hairline footer columns |
| `src/app/(marketing)/components/MiniGraph.tsx` | `'use client'`; lazy 2D Cytoscape thumbnail (decorative, aria-hidden) |
| `src/app/(marketing)/components/Sparkline.tsx` | `'use client'`; lazy recharts line (decorative, aria-hidden) |
| `src/app/(marketing)/components/MarketingNodeCard.tsx` | re-skinned fixture-fed node card (no KnowledgeNode dep) |
| `src/app/(marketing)/sections/*.tsx` | Hero, Problem, Extraction, DualAccess, Enforcement, Performance, TypeSystem, Cost, ClosingCta |
| `src/app/(dashboard)/dashboard/page.tsx` (MOVE) | the relocated overview (content from old `(dashboard)/page.tsx`) |
| `src/app/(dashboard)/page.tsx` (DELETE) | removed to free `/` for marketing |
| `src/app/(auth)/login/actions.ts` (MODIFY) | success `redirect('/')` → `redirect('/dashboard')` |
| `src/components/layout/Sidebar.tsx` (MODIFY) | Dashboard nav `href '/'` → `/dashboard` + active-state check |
| `package.json` (MODIFY) | add `motion` |

---

## Tasks

### Task 0 — Routing prerequisite (free up `/`)
**Files:** move `(dashboard)/page.tsx` → `(dashboard)/dashboard/page.tsx`; modify `(auth)/login/actions.ts`; modify `src/components/layout/Sidebar.tsx`.
- [ ] Create `(dashboard)/dashboard/page.tsx` with the existing overview content; delete `(dashboard)/page.tsx`.
- [ ] `login/actions.ts`: change success `redirect('/')` → `redirect('/dashboard')`.
- [ ] `Sidebar.tsx`: Dashboard item `href:'/'` → `'/dashboard'`; active check `pathname === '/'` → `pathname === '/dashboard'`.
- [ ] **Verify:** `npm run build` compiles with no "two pages resolve to /" error (after Task 1 page exists) — checkpoint after Task 1.

### Task 1 — Foundation: tokens, schema, dict, locale, palette, motion hook
**Interfaces produced:**
- `schema.ts`: `export const NODE_TYPES = [...] as const; export type NodeType = typeof NODE_TYPES[number];` (+ `EDGE_TYPES`/`EdgeType`).
- `dict.ts`: `export const dict = { vi, en }`; `export type Dict = typeof vi`.
- `locale.tsx`: `useT(): (key) => string`, `useLocale(): {locale,setLocale}`, `<LocaleProvider initial>`.
- `graphPalette.ts`: `nodeTint(type): string`, `ACCENT='#5FB8A6'`.
- `useReducedMotion.ts`: `useReducedMotion(): boolean`, `useGraphCapability(): boolean`.
- [ ] `marketing.css`: scope all tokens under `[data-surface="marketing"]` (canvas/surface/accent/accent-foreground/text/muted/hairline/radius), `background-color:#0A0B0D; background-image:none`, and a `.mk-*` utility set if needed. NO neon utilities.
- [ ] `schema.ts` from spec Appendix A (20 node types incl. used subset, 25 edge types).
- [ ] `dict.ts` with all section copy from spec §4 (vi first), `const en = {...} satisfies typeof vi`.
- [ ] `locale.tsx` client provider (cookie `daab_lang`, default `vi`).
- [ ] `graphPalette.ts` zinc tints + teal.
- [ ] `useReducedMotion.ts` (matchMedia + saveData + WebGL2/pointer/idle gate).
- [ ] **Verify:** `tsc` clean (run via `npm run build` later).

### Task 2 — Fixtures + the schema-contract test
- [ ] `fixtures/graph.ts` (≤80 nodes, pre-baked coords, types ∈ schema).
- [ ] `fixtures/content.ts` (mcpTools list of real names, code snippet + extracted `architecture` node `kind:function`, gates, perf NFRs, nodeTypes representative chips, cost diagram values labeled illustrative).
- [ ] `fixtures/fixtures.test.ts`: assert every `node.type`/`edge.type` ∈ `NODE_TYPES`/`EDGE_TYPES`. (Node has no test runner configured → implement as a type-level assertion + a tiny runtime guard executed at import in dev, OR a `*.test.ts` that `tsc` type-checks. Use a `satisfies`-based compile-time guard so `npm run build` fails on drift.)

### Task 3 — Hero WebGL (the one cinematic moment)
- [ ] `StaticConstellation.tsx` (CSS/SVG poster; the unconditional LCP visual).
- [ ] `HeroGraph.tsx` mirroring `KnowledgeGraph.tsx`: `ForceGraph3D` with `backgroundColor` transparent, `nodeColor` from graphPalette, bloom OFF, `linkDirectionalParticles 0`, link opacity ~0.18, `cooldownTicks ~120` then freeze, `setPixelRatio(min(dpr,2))`, IO pause/teardown.
- [ ] `HeroGraphWrapper.tsx`: `'use client'` + `dynamic(()=>import('./HeroGraph'),{ssr:false,loading:()=><StaticConstellation/>})` + `memo`; render poster until `useGraphCapability()` passes post-LCP.
- [ ] Wrap in `<figure>`: canvas `aria-hidden`; figure `aria-label` (vi/en); visually-hidden text equivalent naming 20 node + 25 edge types; keyboard Pause/Play.

### Task 4 — Shared UI atoms
- [ ] `Reveal.tsx`, `CountUp.tsx`, `Cta.tsx`, `LanguageToggle.tsx`, `MarketingNav.tsx`, `MarketingFooter.tsx`, `MarketingNodeCard.tsx`, `MiniGraph.tsx` (lazy, decorative), `Sparkline.tsx` (lazy, decorative).

### Task 5 — The 9 sections + page composition
- [ ] `sections/Hero.tsx` (asymmetric split; copy ≤2 lines / 18-word sub; CTA scroll-to-graph).
- [ ] `sections/Problem.tsx`, `Extraction.tsx` (connector-draw standout), `DualAccess.tsx` (MCP list + MiniGraph), `Enforcement.tsx` (static gate diagram), `Performance.tsx` (CountUp + Sparkline), `TypeSystem.tsx` (20/25/49 chips), `Cost.tsx`, `ClosingCta.tsx`.
- [ ] `page.tsx` composes them; `(marketing)/layout.tsx` reads cookie, sets `<div data-surface="marketing" lang>`, `generateMetadata` (bilingual + OG + alternates + metadataBase), `viewport.themeColor`.

### Task 6 — Verify, review, finish
- [ ] `npm run lint` clean; `npm run build` passes (TS strict, no `any`).
- [ ] Grep `(marketing)` for `.glass|.glow|.text-glow|neon-|graph/styles` → zero matches.
- [ ] Confirm registered MCP tool count vs `schema.go`; adjust badge/fixture if ≠35.
- [ ] QA agents: a11y review (contrast/keyboard/canvas alt/reduced-motion), taste review (vs the bans), correctness review.
- [ ] (Optional) run the app + Lighthouse (LCP/CLS/INP) if a browser is available.
- [ ] Serena checkpoint.

## Success Criteria
1. `npm run build` and `npm run lint` pass.
2. `/` serves the public marketing page; `/dashboard` serves the (auth'd) overview; login redirects to `/dashboard`.
3. No neon/glass/styles.ts leakage in the marketing tree; one WebGL context; hero degrades to the static poster on reduced-motion/mobile/no-WebGL.
4. Every visible string resolves in both vi and en; VI diacritics render; `<div lang>` switches.
5. Accent is the single teal; CTA is near-black-on-teal; canvas has a bilingual text equivalent + keyboard Pause/Play.
6. All on-page numbers match the verified taxonomy.

## Notes / deviations from spec (justified)
- **Providers:** the marketing subtree inherits root providers (can't give it a provider-free layout without editing the shared root). They are inert. Accepted.
- **`<html lang>`:** set on a marketing `<div lang>` (root `<html lang="en">` is shared and unchanged); add `alternates.languages` in metadata for SEO.
- **Root fonts:** add `latin-ext`+`vietnamese` subsets at the root (the only correct place) — beneficial app-wide.
- **Dynamic rendering:** reading `daab_lang` via `cookies()` opts the marketing route into dynamic rendering. Accepted — the static poster is still the LCP element; correctness of vi-first first paint outweighs CDN static caching for this route.
- **Test runner:** no Jest/Vitest configured; the fixtures-vs-schema "test" is a compile-time `satisfies` guard so `npm run build` enforces it.
